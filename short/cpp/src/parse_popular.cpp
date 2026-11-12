// Test 1, C++: the most used JSON library (nlohmann/json), one line at a time, into a struct.

#include <nlohmann/json.hpp>

#include "common.hpp"

using json = nlohmann::json;

struct Record {
  std::string ts;
  std::string method;
  std::string path;
  int status = 0;
  std::uint64_t bytes = 0;
  double duration = 0.0;
};
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(Record, ts, method, path, status, bytes, duration)

int main(int argc, char** argv) {
  if (argc != 3) {
    std::fprintf(stderr, "usage: parse_popular INPUT.jsonl OUTPUT.tsv\n");
    return 2;
  }
  Progress progress;
  // Binary mode: on Windows, text mode would also translate line endings, work Rust doesn't do.
  std::ifstream in(argv[1], std::ios::binary);
  if (!in) {
    std::fprintf(stderr, "cannot open %s\n", argv[1]);
    return 1;
  }
  Totals t;
  std::string line;
  while (std::getline(in, line)) {
    auto r = json::parse(line).get<Record>();
    t.add(r.status, r.bytes, r.duration, r.ts.size() + r.method.size() + r.path.size());
    progress.tick();
  }
  t.write(argv[2]);
  return 0;
}
