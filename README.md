# C++ vs Rust: JSON parsing and three everyday jobs on one log

Code and per-run results behind two Shorts:
- "How much faster is C++ than Rust? 3 tests, and Rust wins one by 7.5x" (`short/`, `results/i7win-20261109`)
- "Is Rust faster than C++? 18x at regex, then C++ wins one" (`everyday/`, `results/everyday-i7win-20261110`)

## The input
Both Shorts read the same web server access log: 5,000,000 JSON lines (about 1 GB), made by `gen/gen_log.py`
with a fixed seed. Every session records the file's sha256 in `meta.json`
(`25d56055a8dbd9d9dcf856f35593ebb0cfd85d24ca1b0089109376efb52829f1`). The IP addresses, ids and user agents in it are
generated.

## What is tested

**JSON Short (`short/`)**, wall time of the whole program under hyperfine:

| Test | C++ | Rust |
|---|---|---|
| 1, most popular library, one line at a time into a struct | nlohmann/json 3.12.0 (`parse_popular.cpp`) | serde_json 1.0.154 (`parse_popular.rs`) |
| 2, fastest library measured, whole file in memory | simdjson 5.1.0 On-Demand (`parse_fastest.cpp`) | serde_json with borrowed strings, simd-json 0.19.0, sonic-rs 0.5.10 (`parse_fastest.rs`) |
| 3, index checks in a loop that reads 5 million numbers in a scrambled order, 40 passes | | `v[i]` and `get_unchecked` (`checks.rs`) |

Test 3 reads `data/durations.bin`, every line's duration as a raw f64 (`short/tools/durations.py`).

**Everyday Short (`everyday/`)**, each language with the tool it reaches for first:

| Job | C++ (`everyday.cpp`) | Rust (`main.rs`) |
|---|---|---|
| 1, find every 5xx on an `/api/<name>/<id>` path and capture the path, one search per line | `std::regex` + `std::regex_search` | `regex::Regex::captures` (regex 1.13.1) |
| 2, sort the 5,000,000 requests by duration | `std::sort` with a lambda | `sort_unstable_by` with `total_cmp` |
| 3, group by path, count each group and take its p99 duration | `std::unordered_map` per chunk with `std::transform(std::execution::par, ...)` | `HashMap` with a Rayon 1.12.0 `par_iter().fold().reduce()` |

Regex: `"path":"(/api/[a-z]+/[0-9]+)","status":5[0-9][0-9]`. Jobs 2 and 3 read `data/records.bin` (duration, status,
bytes and path per line, written by `everyday/tools/records.py`), so JSON parsing stays out of these numbers. Each
program times its own load (read the file, build the records) apart from the job and writes both per run; the Short's
times are the job alone.

Every program writes a digest of its result (count plus FNV-1a, or the per-path rows for job 3). The sessions stop
unless both languages write byte-identical output.

## Setup
From `results/*/meta.json` and the build files:
- **Machine:** Intel i7-13700F, RTX 4070 PC, Windows 11 (native, no Docker), power plan Balanced.
- **Compilers:** clang 23.1.5 against Microsoft's STL (Visual Studio 2022), CMake Release (`-O3 -DNDEBUG`) plus
  `-march=native`. rustc 1.99.1, cargo's default release profile plus `target-cpu=native`. No LTO on either side.
- **Timing:** hyperfine 2.0.0, `-N`, 1 warm-up run.
- **Pinning:** every cell runs pinned to logical CPU 4, one performance core (`tools/pin.py`). The 8-core rows of job 3
  run on CPUs 0, 2, 4, 6, 8, 10, 12, 14 (one thread on each performance core).
- **Runs:** 5 recorded rounds (hyperfine's screen recorded as an asciinema cast, `round*/*.cast`) plus one plain round
  without the recorder. Which language goes first alternates every round. JSON session: 10 runs per cell per round, so
  50 runs per cell. Everyday session: 10 runs per cell per round, 3 for `std::regex` (15 in total).
- **Quiet machine:** before every cell the session waits until the cell's cores and their SMT siblings are idle and the
  machine is under 20% CPU. The reading is saved as `busy_before` in `runs.jsonl`.

## Results
Medians over every run of the 5 recorded rounds. All numbers are in `results/<session>/summary.json`, made from
`runs.jsonl` by `tools/summary.py`.

**JSON Short, wall time in seconds** (`results/i7win-20261109/summary.json`, `runs_s_median`)

| Test | C++ | Rust | |
|---|---|---|---|
| 1, most popular library | nlohmann/json 13.6608 | serde_json 1.8164 | Rust 7.5x faster |
| 2, fastest library | simdjson 0.6055 | serde_json 1.2586 · sonic-rs 1.3962 · simd-json 1.4105 | C++ 2.1x faster than serde_json |
| 3, index checks | | `v[i]` 0.9979 · `get_unchecked` 0.9904 | checks cost 0.8% |

**Everyday Short, the job alone in milliseconds** (`results/everyday-i7win-20261110/summary.json`, `job_s_median`)

| Job | C++ | Rust | |
|---|---|---|---|
| 1, regex, one search per line | `std::regex` 11,980.9 | regex 671.3 | Rust 17.8x faster |
| 2, sort by duration | `std::sort` 215.5 | `sort_unstable_by` 175.3 | Rust 1.23x faster |
| 3, group + p99, 1 core | 242.6 | 482.3 | C++ 1.99x faster |
| 3, group + p99, 8 cores | 104.2 | 105.9 | |

Job 1 finds 57,337 matching lines out of 5,000,000 (`round*/rust-regex-lines.out`). Rayon starts 24 threads by
default under both CPU masks (`rayon_threads` in `meta.json`). The same file keeps hyperfine's wall time
(`runs_s_median`) and the load time (`load_s_median`) for every cell, and the plain round's medians next to them.

## Reproduce
On Windows with Git Bash, Visual Studio 2022 (Build Tools, C++ workload), LLVM/clang, CMake, Ninja, Rust (stable,
rustup's default location), hyperfine on `PATH`, and Python 3 with `psutil` and `pywinpty`. CMake downloads
nlohmann/json and simdjson. From the repo root:
```bash
mkdir -p data
python gen/gen_log.py data/log.jsonl                     # 5,000,000 lines, prints the sha256 to compare with meta.json
python short/tools/durations.py data/log.jsonl data/durations.bin
python everyday/tools/records.py data/log.jsonl data/records.bin
cmd //c short\\build.cmd
cmd //c everyday\\build.cmd
python short/tools/session.py results/my-json-session 5      # 5 recorded rounds + 1 plain round
python everyday/tools/session.py results/my-everyday-session 5
python tools/summary.py results/my-json-session
python tools/summary.py results/my-everyday-session
```
The build scripts expect Visual Studio 2022 Community at its default path; change the `vcvars64.bat` line for another
edition. Set `HYPERFINE` if hyperfine is not on `PATH`.

## Settings people may argue about
- Every job uses the tool each language reaches for first, with default settings: `std::regex` from the standard
  library and the `regex` crate in job 1, `std::sort` and `sort_unstable_by` in job 2, `std::execution::par` and Rayon
  with its default thread count in job 3.
- Test 1 of the JSON Short uses the most popular library on each side: nlohmann/json has the most GitHub stars of the
  C++ JSON libraries, serde_json the most crates.io downloads.
- The C++ side uses Microsoft's STL, which runs `std::execution::par` on the Windows thread pool. Rayon sizes its pool
  from the machine's logical CPU count (24), even when the process is pinned to one core.
- Job 1 runs one regex search per line on both sides.
- Both sides build for the CPU they run on (`-march=native`, `target-cpu=native`) with no LTO.
- The 1-core rows pin everything to one performance core, including the parallel code in job 3.
