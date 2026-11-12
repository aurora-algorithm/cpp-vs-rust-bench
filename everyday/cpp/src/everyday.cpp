// Everyday jobs on the same log, C++ side. Byte for byte the same output as ../rust/src/main.rs.
// usage: everyday regex|sort|agg INPUT OUTPUT OPTION
//   regex reads the raw JSON-lines log; sort and agg read records.bin (tools/records.py).
// Loading the input (reading the file, building the records) is timed apart from the job. Both times go to the file
// named by BENCH_TIMES, one JSON line per run, because hyperfine discards the program's stdout. The output is a
// digest (count + FNV-1a), so writing it costs next to nothing inside hyperfine's wall time.

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <version>
#if defined(__cpp_lib_execution) && __cpp_lib_execution >= 201902L
#include <execution>
#define PAR std::execution::par,
static constexpr bool HAVE_PAR = true;
#else
// A standard library without parallel algorithms (Apple's libc++) builds a sequential copy for output checks only.
#define PAR
static constexpr bool HAVE_PAR = false;
#endif
#include <regex>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>
#include <tuple>
#include <unordered_map>
#include <vector>

using Clock = std::chrono::steady_clock;

// 5xx responses on /api/<collection>/<id> routes; the capture is the path.
static const char* const PATTERN = R"re("path":"(/api/[a-z]+/[0-9]+)","status":5[0-9][0-9])re";

struct Record {
  std::string path;
  double duration;
  std::uint16_t status;
  std::uint64_t bytes;
};

struct Times {
  double load_s = 0.0;
  double job_s = 0.0;
};

struct Fnv {
  std::uint64_t h = 0xcbf29ce484222325ULL;
  void add(const void* p, std::size_t n) {
    const auto* b = static_cast<const unsigned char*>(p);
    for (std::size_t i = 0; i < n; ++i) h = (h ^ b[i]) * 0x100000001b3ULL;
  }
  void add_u64(std::uint64_t x) {
    unsigned char b[8];
    for (int i = 0; i < 8; ++i) b[i] = static_cast<unsigned char>(x >> (8 * i));
    add(b, 8);
  }
  void add_f64(double d) {
    std::uint64_t x;
    std::memcpy(&x, &d, 8);
    add_u64(x);
  }
  std::string line(std::size_t count) const { return std::to_string(count) + "\t" + std::to_string(h) + "\n"; }
};

static double since(Clock::time_point t) { return std::chrono::duration<double>(Clock::now() - t).count(); }

static std::string read_file(const char* path) {
  std::ifstream in(path, std::ios::binary | std::ios::ate);
  if (!in) throw std::runtime_error(std::string("cannot open ") + path);
  std::string data(static_cast<std::size_t>(in.tellg()), '\0');
  in.seekg(0);
  in.read(data.data(), static_cast<std::streamsize>(data.size()));
  if (!in) throw std::runtime_error(std::string("cannot read ") + path);
  return data;
}

template <class T>
static T take(const std::string& d, std::size_t& at) {
  if (at + sizeof(T) > d.size()) throw std::runtime_error("records.bin is truncated");
  T x;
  std::memcpy(&x, d.data() + at, sizeof(T));
  at += sizeof(T);
  return x;
}

// records.bin: per record f64 duration, u16 status, u64 bytes, u16 path length, path bytes (little endian).
static std::vector<Record> parse_records(const std::string& d) {
  std::vector<Record> out;
  std::size_t at = 0;
  while (at < d.size()) {
    Record r;
    r.duration = take<double>(d, at);
    r.status = take<std::uint16_t>(d, at);
    r.bytes = take<std::uint64_t>(d, at);
    const auto len = take<std::uint16_t>(d, at);
    if (at + len > d.size()) throw std::runtime_error("records.bin is truncated");
    r.path.assign(d.data() + at, len);
    at += len;
    out.push_back(std::move(r));
  }
  return out;
}

using Found = std::vector<std::pair<std::size_t, std::string_view>>;

static Found regex_lines(std::string_view text) {
  const std::regex re(PATTERN);
  Found found;
  std::cmatch m;
  std::size_t start = 0;
  while (start < text.size()) {
    std::size_t end = text.find('\n', start);
    if (end == std::string_view::npos) end = text.size();
    if (std::regex_search(text.data() + start, text.data() + end, m, re)) {
      found.emplace_back(start + m.position(1), std::string_view(m[1].first, m[1].second));
    }
    start = end + 1;
  }
  return found;
}

using Groups = std::unordered_map<std::string_view, std::vector<double>>;
using Row = std::tuple<std::string_view, std::size_t, double>;

// Count + p99 duration per path: one map per chunk in parallel, one merge pass, then the p99s in parallel.
static std::vector<Row> agg(const std::vector<Record>& records) {
  constexpr std::size_t CHUNKS = 256;
  const std::size_t step = (records.size() + CHUNKS - 1) / CHUNKS;
  std::vector<std::span<const Record>> chunks;
  for (std::size_t i = 0; i < records.size(); i += step) {
    chunks.emplace_back(records.data() + i, std::min(step, records.size() - i));
  }
  std::vector<Groups> partial(chunks.size());
  std::transform(PAR chunks.begin(), chunks.end(), partial.begin(), [](std::span<const Record> chunk) {
    Groups g;
    for (const Record& r : chunk) g[r.path].push_back(r.duration);
    return g;
  });
  Groups groups = std::move(partial.front());
  for (std::size_t c = 1; c < partial.size(); ++c) {
    for (auto& [path, d] : partial[c]) {
      auto& into = groups[path];
      into.insert(into.end(), d.begin(), d.end());
    }
  }
  std::vector<Groups::value_type*> items;
  items.reserve(groups.size());
  for (auto& kv : groups) items.push_back(&kv);
  std::vector<Row> rows(items.size());
  std::transform(PAR items.begin(), items.end(), rows.begin(), [](Groups::value_type* kv) {
    auto& d = kv->second;
    const std::size_t i = (d.size() - 1) * 99 / 100;
    std::nth_element(d.begin(), d.begin() + i, d.end());
    return Row{kv->first, d.size(), d[i]};
  });
  return rows;
}

static std::string durations_digest(const std::vector<Record>& recs) {
  Fnv f;
  for (const Record& r : recs) f.add_f64(r.duration);
  return f.line(recs.size());
}

static std::string regex_job(std::string_view option, const std::string& data, Times& t) {
  if (option != "std") throw std::invalid_argument("unknown regex option");
  const auto t0 = Clock::now();
  const Found found = regex_lines(data);
  t.job_s = since(t0);
  Fnv f;
  for (const auto& [off, path] : found) {
    f.add_u64(off);
    f.add(path.data(), path.size());
  }
  return f.line(found.size());
}

static std::string records_job(std::string_view mode, std::string_view option, std::vector<Record>& recs, Times& t) {
  const auto by_duration = [](const Record& a, const Record& b) { return a.duration < b.duration; };
  if (mode == "sort" && option == "duration") {
    const auto t0 = Clock::now();
    std::sort(recs.begin(), recs.end(), by_duration);
    t.job_s = since(t0);
    return durations_digest(recs);
  }
  if (mode == "agg" && option == "par") {
    const auto t0 = Clock::now();
    std::vector<Row> rows = agg(recs);
    t.job_s = since(t0);
    std::sort(rows.begin(), rows.end(), [](const Row& a, const Row& b) { return std::get<0>(a) < std::get<0>(b); });
    std::string out;
    char num[64];
    for (const auto& [path, n, p99] : rows) {
      std::snprintf(num, sizeof num, "\t%zu\t%.6f\n", n, p99);
      out.append(path).append(num);
    }
    return out;
  }
  throw std::invalid_argument("unknown mode/option");
}

static void append_times(const Times& t) {
  const char* path = std::getenv("BENCH_TIMES");
  if (!path) return;
  std::FILE* f = std::fopen(path, "a");
  if (!f) throw std::runtime_error("cannot open BENCH_TIMES");
  std::fprintf(f, "{\"load_s\": %.6f, \"job_s\": %.6f, \"par\": %d}\n", t.load_s, t.job_s, HAVE_PAR);
  std::fclose(f);
}

int main(int argc, char** argv) {
  if (argc != 5) {
    std::fprintf(stderr, "usage: %s regex|sort|agg INPUT OUTPUT OPTION\n", argv[0]);
    return 2;
  }
  const std::string_view mode = argv[1], option = argv[4];
  try {
    Times t;
    const auto t0 = Clock::now();
    std::string data = read_file(argv[2]);
    std::string out;
    if (mode == "regex") {
      t.load_s = since(t0);
      out = regex_job(option, data, t);
    } else {
      std::vector<Record> recs = parse_records(data);
      data = std::string();
      t.load_s = since(t0);
      out = records_job(mode, option, recs, t);
    }
    std::ofstream f(argv[3], std::ios::binary);
    f << out;
    f.close();
    if (!f) throw std::runtime_error("cannot write output");
    append_times(t);
    std::printf("{\"load_s\": %.6f, \"job_s\": %.6f}\n", t.load_s, t.job_s);
  } catch (const std::exception& e) {
    std::fprintf(stderr, "error: %s\n", e.what());
    return 1;
  }
  return 0;
}
