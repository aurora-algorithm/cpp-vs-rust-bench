#pragma once

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <string>
#include <vector>

// Same text, byte for byte, as rust/src/lib.rs, so the harness can compare the outputs.
struct Totals {
  std::uint64_t lines = 0;
  std::uint64_t status_sum = 0;
  std::uint64_t bytes = 0;
  std::uint64_t text_len = 0;
  double duration = 0.0;

  void add(std::int64_t status, std::uint64_t b, double d, std::size_t text) {
    lines += 1;
    status_sum += static_cast<std::uint64_t>(status);
    bytes += b;
    text_len += text;
    duration += d;
  }

  void write(const char* path) const {
    std::ofstream out(path, std::ios::binary);
    out << lines << '\t' << status_sum << '\t' << bytes << '\t' << text_len << '\t' << std::fixed
        << std::setprecision(6) << duration << '\n';
  }
};

// For the race chart: the time since start every 65,536 lines, written only when PROGRESS_OUT is set.
// Both languages do the same work per line here (one increment and one compare).
class Progress {
 public:
  void tick() {
    if ((++lines_ & 0xFFFF) == 0) {
      marks_.push_back(elapsed());
    }
  }

  ~Progress() {
    const char* path = std::getenv("PROGRESS_OUT");
    if (path == nullptr) {
      return;
    }
    std::ofstream out(path, std::ios::binary);
    out << std::fixed << std::setprecision(6);
    for (std::size_t i = 0; i < marks_.size(); ++i) {
      out << (i + 1) * 65536 << '\t' << marks_[i] << '\n';
    }
    out << lines_ << '\t' << elapsed() << '\n';
  }

 private:
  using Clock = std::chrono::steady_clock;
  double elapsed() const { return std::chrono::duration<double>(Clock::now() - start_).count(); }
  Clock::time_point start_ = Clock::now();
  std::uint64_t lines_ = 0;
  std::vector<double> marks_;
};
