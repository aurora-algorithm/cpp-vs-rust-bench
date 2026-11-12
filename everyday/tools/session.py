#!/usr/bin/env python3
"""The everyday-jobs measurement session (C++ vs Rust), natively on Windows (i7-13700F).

Every cell runs under hyperfine (1 warm-up, N runs, no shell) pinned to its CPUs, inside a pseudo-console so the
live screen is recorded as a cast. Rounds alternate which language goes first. The programs also write their own
load and job times per run (BENCH_TIMES), so a chart can split hyperfine's wall time into "reading the input" and
"the job". A final round runs without the recorder, to check that recording didn't move the numbers. Outputs (a
count + FNV-1a digest) must be byte-identical across both languages within each output group.

usage: python everyday/tools/session.py RESULTS_DIR [ROUNDS=5]     (from the repo root)
env:   BENCH_LOG / BENCH_RECORDS  a small log + its records.bin, only for a pilot
       BENCH_RUNS                 hyperfine runs per cell (default 10; std::regex gets REGEX_STD_RUNS)
       BENCH_NO_GATE=1            skip the quiet-machine gate (pilot only)
"""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil

# Logical 0-15 are the 8 performance cores (SMT pairs 0/1, 2/3, ...), 16-23 the efficiency cores.
ONE_CORE = [4]
ALL_CORES = [0, 2, 4, 6, 8, 10, 12, 14]  # one thread on each of the 8 performance cores; siblings and E-cores idle
HYPERFINE = os.environ.get("HYPERFINE") or shutil.which("hyperfine") or "hyperfine"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PY = str(Path(sys.executable).with_name("python.exe"))
TOOLS = Path(__file__).resolve().parent
CPP = "everyday/cpp/build/everyday.exe"
RUST = "everyday/rust/target/release/everyday.exe"
LOG = os.environ.get("BENCH_LOG", "data/log.jsonl")
RECORDS = os.environ.get("BENCH_RECORDS", "data/records.bin")
RUNS = int(os.environ.get("BENCH_RUNS", "10"))
REGEX_STD_RUNS = int(os.environ.get("BENCH_REGEX_STD_RUNS", "3"))  # std::regex takes many seconds per run
WARMUP = 1
COLS, ROWS = 52, 4  # the same cast size as the JSON session

# (cell, test, output group, side, hyperfine label, program, mode, input, option, cpus, runs)
CELLS = [
    ("cpp-regex-std", 1, "regex", "cpp", "C++ std::regex", CPP, "regex", LOG, "std", ONE_CORE, REGEX_STD_RUNS),
    ("rust-regex-lines", 1, "regex", "rust", "Rust regex", RUST, "regex", LOG, "lines", ONE_CORE, RUNS),
    ("cpp-sort-duration", 2, "durations", "cpp", "C++ std::sort", CPP, "sort", RECORDS, "duration", ONE_CORE, RUNS),
    ("rust-sort-duration", 2, "durations", "rust", "Rust sort_unstable_by", RUST, "sort", RECORDS, "duration", ONE_CORE, RUNS),
    ("cpp-agg-1core", 3, "agg", "cpp", "C++ p99 per path, 1 core", CPP, "agg", RECORDS, "par", ONE_CORE, RUNS),
    ("rust-agg-1core", 3, "agg", "rust", "Rust p99 per path, 1 core", RUST, "agg", RECORDS, "par", ONE_CORE, RUNS),
    ("cpp-agg-8cores", 3, "agg", "cpp", "C++ p99 per path, 8 cores", CPP, "agg", RECORDS, "par", ALL_CORES, RUNS),
    ("rust-agg-8cores", 3, "agg", "rust", "Rust p99 per path, 8 cores", RUST, "agg", RECORDS, "par", ALL_CORES, RUNS),
]


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def siblings(cpus: list[int]) -> set[int]:
    return {c ^ 1 for c in cpus if c < 16} | set(cpus)


def quiet_gate(cpus: list[int], max_wait: int = 1800) -> dict:
    """Waits until the cell's cores and their hyperthread siblings are idle (under 5% over 5 s) and the whole
    machine is under 20%; returns that reading. Gives up with an error after max_wait: a busy machine voids the
    numbers, so the session never measures through it."""
    if os.environ.get("BENCH_NO_GATE") == "1":
        return {"gate": "skipped"}
    waited = 0
    while True:
        per = psutil.cpu_percent(interval=5, percpu=True)
        cores = {c: per[c] for c in sorted(siblings(cpus))}
        reading = {"max_core": max(cores.values()), "mean_core": sum(cores.values()) / len(cores), "total": sum(per) / len(per)}
        # Over many cores one hopping Windows background thread (6-12%) never lets every core pass 5%.
        quiet = reading["max_core"] < 5 if len(cores) <= 2 else reading["mean_core"] < 5 and reading["max_core"] < 15
        if quiet and reading["total"] < 20:
            return reading
        if waited >= max_wait:
            raise RuntimeError(f"machine stayed busy for {max_wait} s: {reading} {cores}")
        if waited % 300 == 0:
            log(f"machine busy {reading}, waiting")
        waited += 5


def wall_times(report: dict) -> list[float]:
    """Wall-clock seconds of every run in a hyperfine 2.x export (schema_version 2)."""
    out = []
    for m in report["results"][0]["measurements"]:
        t = m["time_wall_clock"]
        if t["unit"] != "second" or m["exit_code"] != 0:
            raise RuntimeError(f"unexpected measurement {m}")
        out.append(t["value"])
    return out


def own_times(path: Path, runs: int) -> list[dict]:
    """The programs' own load/job times, warm-up dropped."""
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    if len(rows) != WARMUP + runs:
        raise RuntimeError(f"{path}: {len(rows)} timing lines, expected {WARMUP + runs}")
    return rows[WARMUP:]


def order_for(round_no: int) -> list[tuple]:
    """Each test's cells, C++ first in odd rounds and Rust first in even ones, rivals kept next to each other."""
    first = "cpp" if round_no % 2 == 1 else "rust"
    cells = []
    for i in range(0, len(CELLS), 2):
        pair = CELLS[i:i + 2]
        cells += sorted(pair, key=lambda c: c[3] != first)
    return cells


def run_cell(cell: tuple, rdir: Path, record: bool) -> dict:
    name, test, group, side, label, prog, mode, inp, option, cpus, runs = cell
    out = rdir / f"{name}.out"
    times = rdir / f"{name}.times.jsonl"
    export = rdir / f"{name}.json"
    # Forward slashes: hyperfine -N splits the command like a POSIX shell, where a backslash is an escape.
    argv = [prog, mode, inp, out.as_posix(), option]
    hf = [HYPERFINE, "-N", "--warmup", str(WARMUP), "--runs", str(runs), "-n", label, "--export-json", str(export),
          subprocess.list2cmdline(argv)]
    pinned = [PY, str(TOOLS / "pin.py"), ",".join(map(str, cpus)), *hf]
    env = dict(os.environ, BENCH_TIMES=str(times))
    busy = quiet_gate(cpus)
    t0 = time.time()
    if record:
        rc = subprocess.call([PY, str(TOOLS / "cast.py"), str(rdir / f"{name}.cast"), str(COLS), str(ROWS), "--",
                              *pinned], env=env, creationflags=NO_WINDOW)
    else:
        rc = subprocess.call(pinned, env=env, stdout=subprocess.DEVNULL, creationflags=NO_WINDOW)
    if rc != 0 or not export.exists():
        raise RuntimeError(f"{name}: hyperfine failed ({rc})")
    own = own_times(times, runs)
    return {"cell": name, "test": test, "group": group, "side": side, "label": label, "cpus": cpus,
            "runs_s": wall_times(json.loads(export.read_text())), "load_s": [r["load_s"] for r in own],
            "job_s": [r["job_s"] for r in own], "par": [r.get("par") for r in own], "busy_before": busy,
            "busy_after": psutil.cpu_percent(interval=1), "started": t0,
            "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}


def versions() -> dict:
    def cmd(*a: str) -> str:
        return subprocess.run(a, capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip()
    lock = Path("everyday/rust/Cargo.lock").read_text()
    crates = {}
    for block in lock.split("[[package]]")[1:]:
        fields = dict((k.strip(), v.strip().strip('"')) for k, v in
                      (ln.split("=", 1) for ln in block.strip().splitlines() if "=" in ln))
        if fields.get("name") in {"regex", "regex-automata", "rayon"}:
            crates[fields["name"]] = fields.get("version")
    cache = Path("everyday/cpp/build/CMakeCache.txt").read_text(errors="replace").splitlines()
    return {
        "rustc": cmd(os.path.expanduser("~/.cargo/bin/rustc.exe"), "-vV"),
        "clang": cmd(r"C:\Program Files\LLVM\bin\clang++.exe", "--version").splitlines()[0],
        "cmake_cxx": [x for x in cache if x.startswith(("CMAKE_CXX_COMPILER:", "CMAKE_CXX_FLAGS_RELEASE:"))],
        "msvc_toolset": os.environ.get("VCToolsVersion", "see build.log"),
        "crates": crates,
        "hyperfine": cmd(HYPERFINE, "--version"),
        "os": platform.platform(),
        "cpu": platform.processor(),
        "power_plan": cmd("powercfg", "/getactivescheme"),
    }


def check_outputs(all_runs: list[dict]) -> None:
    for group in {x["group"] for x in all_runs}:
        shas = {x["sha256"] for x in all_runs if x["group"] == group}
        if len(shas) != 1:
            raise RuntimeError(f"output group {group}: outputs differ between cells")


def rayon_threads(cpus: list[int]) -> int:
    """How many threads Rayon starts by default under this affinity mask (recorded, not set)."""
    r = subprocess.run([PY, str(TOOLS / "pin.py"), ",".join(map(str, cpus)), RUST, "agg", RECORDS, os.devnull, "par"],
                       capture_output=True, text=True, creationflags=NO_WINDOW, env={k: v for k, v in os.environ.items() if k != "BENCH_TIMES"})
    return json.loads(r.stdout)["threads"]


def main() -> int:
    results = Path(sys.argv[1])
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    results.mkdir(parents=True, exist_ok=False)
    meta = {"versions": versions(), "rounds": rounds, "runs": RUNS, "regex_std_runs": REGEX_STD_RUNS,
            "one_core": ONE_CORE, "all_cores": ALL_CORES, "log": LOG, "records": RECORDS,
            "log_sha256": hashlib.sha256(Path(LOG).read_bytes()).hexdigest(),
            "records_sha256": hashlib.sha256(Path(RECORDS).read_bytes()).hexdigest(),
            "rayon_threads": {"1core": rayon_threads(ONE_CORE), "8cores": rayon_threads(ALL_CORES)},
            "started": time.ctime()}
    (results / "meta.json").write_text(json.dumps(meta, indent=2))
    log("waiting for a quiet machine (up to 4 h)")
    quiet_gate(ALL_CORES, max_wait=4 * 3600)
    all_runs = []
    for r in range(1, rounds + 2):
        record = r <= rounds
        rdir = results / (f"round{r}" if record else "plain")
        rdir.mkdir()
        log(f"round {r} ({'recorded' if record else 'plain'})")
        for cell in order_for(r):
            res = run_cell(cell, rdir, record)
            res["round"] = r if record else "plain"
            all_runs.append(res)
            med = sorted(res["job_s"])[len(res["job_s"]) // 2]
            wall = sorted(res["runs_s"])[len(res["runs_s"]) // 2]
            log(f"  {res['cell']:20s} job {med:.3f} s  wall {wall:.3f} s")
            with open(results / "runs.jsonl", "a") as f:
                f.write(json.dumps(res) + "\n")
            check_outputs(all_runs)
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
