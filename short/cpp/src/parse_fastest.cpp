// Test 2, C++: the fastest JSON library we know of (simdjson On-Demand), the whole file in memory.

#include <simdjson.h>

#include "common.hpp"

int main(int argc, char** argv) {
  if (argc != 3) {
    std::fprintf(stderr, "usage: parse_fastest INPUT.jsonl OUTPUT.tsv\n");
    return 2;
  }
  Progress progress;
  try {
    auto data = simdjson::padded_string::load(argv[1]).value();
    simdjson::ondemand::parser parser;
    Totals t;
    simdjson::ondemand::document_stream docs = parser.iterate_many(data);
    for (auto doc : docs) {
      simdjson::ondemand::object r = doc.get_object();
      std::string_view ts = r["ts"];
      std::string_view method = r["method"];
      std::string_view path = r["path"];
      std::int64_t status = r["status"];
      std::uint64_t bytes = r["bytes"];
      double duration = r["duration"];
      t.add(status, bytes, duration, ts.size() + method.size() + path.size());
      progress.tick();
    }
    t.write(argv[2]);
  } catch (const std::exception& e) {
    std::fprintf(stderr, "error: %s\n", e.what());
    return 1;
  }
  return 0;
}
