#!/usr/bin/env python3
"""The JSON-parsing measurement session, natively on Windows (i7-13700F).

Every cell runs under hyperfine (1 warm-up, 10 runs, no shell) pinned to one performance core, inside a
pseudo-console so the live screen is recorded as a cast. Rounds alternate which language goes first. After each
cell, one more run logs progress (time every 65,536 lines) for the race chart. A final round runs without the
recorder, to check that recording didn't move the numbers.

usage: python short/tools/session.py RESULTS_DIR [ROUNDS=5]     (from the repo root)
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

PINNED_CPU = 4
# logical CPU 4 is a performance core (EfficiencyClass 1 in GetSystemCpuSetInformation); 16-23 are E-cores
HYPERFINE = os.environ.get("HYPERFINE") or shutil.which("hyperfine") or "hyperfine"
# Children get a hidden console (no window on the desktop), and the helpers run under the console
# python so hyperfine can draw into the recorder.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PY = str(Path(sys.executable).with_name("python.exe"))
CPP = "short/cpp/build"
RUST = "short/rust/target/release"
LOG = os.environ.get("BENCH_LOG", "data/log.jsonl")  # a small file only for a pilot
DUR = os.environ.get("BENCH_DUR", "data/durations.bin")
COLS, ROWS = 52, 4  # 52 columns still fit hyperfine's progress line and final stats; text stays readable in the cast

# (cell, test, side, label shown by hyperfine, argv)
CELLS = [
    ("cpp-popular", 1, "cpp", "C++ nlohmann/json", [f"{CPP}/parse_popular.exe", LOG, "{out}"]),
    ("rust-popular", 1, "rust", "Rust serde_json", [f"{RUST}/parse_popular.exe", LOG, "{out}"]),
    ("cpp-fastest", 2, "cpp", "C++ simdjson", [f"{CPP}/parse_fastest.exe", LOG, "{out}"]),
    ("rust-fastest-serde", 2, "rust", "Rust serde_json", [f"{RUST}/parse_fastest.exe", LOG, "{out}", "serde"]),
    ("rust-fastest-simd", 2, "rust", "Rust simd-json", [f"{RUST}/parse_fastest.exe", LOG, "{out}", "simd"]),
    ("rust-fastest-sonic", 2, "rust", "Rust sonic-rs", [f"{RUST}/parse_fastest.exe", LOG, "{out}", "sonic"]),
    ("rust-checks-on", 3, "rust", "Rust v[i], checked", [f"{RUST}/checks.exe", DUR, "{out}", "index"]),
    ("rust-checks-off", 3, "rust", "Rust get_unchecked", [f"{RUST}/checks.exe", DUR, "{out}", "unchecked"]),
]
PROGRESS_TESTS = {1, 2}


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def quiet_gate(max_wait: int = 1800) -> dict:
    """Waits until the pinned core and its hyperthread sibling are idle (under 5% over 5 s) and the whole machine
    is under 20%; returns that reading. Gives up with an error after max_wait: a busy machine voids the
    numbers, so the session never measures through it. BENCH_NO_GATE=1 skips it (pilot only)."""
    if os.environ.get("BENCH_NO_GATE") == "1":
        return {"gate": "skipped"}
    waited = 0
    while True:
        per = psutil.cpu_percent(interval=5, percpu=True)
        reading = {"core": per[PINNED_CPU], "sibling": per[PINNED_CPU + 1], "total": sum(per) / len(per)}
        if reading["core"] < 5 and reading["sibling"] < 5 and reading["total"] < 20:
            return reading
        if waited >= max_wait:
            raise RuntimeError(f"machine stayed busy for {max_wait} s: {reading}")
        if waited % 300 == 0:
            log(f"machine busy {reading}, waiting")
        waited += 5


def pinned(argv: list[str]) -> list[str]:
    return [PY, str(Path(__file__).with_name("pin.py")), str(PINNED_CPU), *argv]


def hyperfine(label: str, argv: list[str], export: Path) -> list[str]:
    cmd = subprocess.list2cmdline(argv)
    return [HYPERFINE, "-N", "--warmup", "1", "--runs", "10", "-n", label, "--export-json", str(export), cmd]


def wall_times(report: dict) -> list[float]:
    """Wall-clock seconds of every run in a hyperfine 2.x export (schema_version 2)."""
    out = []
    for m in report["results"][0]["measurements"]:
        t = m["time_wall_clock"]
        if t["unit"] != "second" or m["exit_code"] != 0:
            raise RuntimeError(f"unexpected measurement {m}")
        out.append(t["value"])
    return out


def order_for(round_no: int) -> list[tuple]:
    """Each test's cells, C++ first in odd rounds and Rust first in even ones."""
    cells = []
    for test in (1, 2, 3):
        group = [c for c in CELLS if c[1] == test]
        first = "cpp" if round_no % 2 == 1 else "rust"
        cells += sorted(group, key=lambda c: c[2] != first)
    return cells


def run_cell(cell: tuple, rdir: Path, record: bool) -> dict:
    name, test, side, label, argv = cell
    out = rdir / f"{name}.out"
    # Forward slashes: hyperfine -N splits the command like a POSIX shell, where a backslash is an escape.
    real = [a.replace("{out}", out.as_posix()) for a in argv]
    export = rdir / f"{name}.json"
    hf = pinned(hyperfine(label, real, export))
    busy = quiet_gate()
    t0 = time.time()
    if record:
        cast = rdir / f"{name}.cast"
        rc = subprocess.call([PY, str(Path(__file__).with_name("cast.py")), str(cast), str(COLS), str(ROWS), "--", *hf],
                             creationflags=NO_WINDOW)
    else:
        rc = subprocess.call(hf, stdout=subprocess.DEVNULL, creationflags=NO_WINDOW)
    if rc != 0 or not export.exists():
        raise RuntimeError(f"{name}: hyperfine failed ({rc})")
    runs = wall_times(json.loads(export.read_text()))
    result = {"cell": name, "test": test, "side": side, "label": label, "runs_s": runs, "busy_before": busy,
              "started": t0, "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}
    if record and test in PROGRESS_TESTS:
        env = dict(os.environ, PROGRESS_OUT=str(rdir / f"{name}.progress.tsv"))
        subprocess.check_call(pinned(real), env=env, stdout=subprocess.DEVNULL, creationflags=NO_WINDOW)
    return result


def versions() -> dict:
    def cmd(*a: str) -> str:
        return subprocess.run(a, capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip()
    return {
        "rustc": cmd(os.path.expanduser("~/.cargo/bin/rustc.exe"), "-vV"),
        "clang": cmd(r"C:\Program Files\LLVM\bin\clang++.exe", "--version").splitlines()[0],
        "hyperfine": cmd(HYPERFINE, "--version"),
        "os": platform.platform(),
        "cpu": platform.processor(),
        "power_plan": cmd("powercfg", "/getactivescheme"),
    }


def main() -> int:
    results = Path(sys.argv[1])
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    results.mkdir(parents=True, exist_ok=False)
    (results / "meta.json").write_text(json.dumps(
        {"versions": versions(), "rounds": rounds, "pinned_cpu": PINNED_CPU, "log": LOG,
         "log_sha256": hashlib.sha256(Path(LOG).read_bytes()).hexdigest(), "started": time.ctime()}, indent=2))
    log("waiting for a quiet machine (up to 4 h)")
    quiet_gate(max_wait=4 * 3600)
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
            med = sorted(res["runs_s"])[len(res["runs_s"]) // 2]
            log(f"  {res['cell']:20s} median {med:.3f} s")
            with open(results / "runs.jsonl", "a") as f:
                f.write(json.dumps(res) + "\n")
        for test in (1, 2, 3):
            shas = {x["sha256"] for x in all_runs if x["test"] == test}
            if len(shas) != 1:
                raise RuntimeError(f"test {test}: outputs differ")
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
