#!/usr/bin/env python3
"""Per-cell medians over every run of the recorded rounds, plus the plain (unrecorded) round, for one session.

usage: python3 tools/summary.py results/<session>   (writes results/<session>/summary.json)
Wall time is hyperfine's. Sessions from everyday/ also carry job_s and load_s, the programs' own timers.
"""

import json
import statistics
import sys
from pathlib import Path

TIMERS = ("runs_s", "job_s", "load_s")


def cell_summary(rows: list[dict]) -> dict:
    recorded = [r for r in rows if r["round"] != "plain"]
    plain = [r for r in rows if r["round"] == "plain"]
    out = {
        "label": rows[0]["label"],
        "recorded_runs": sum(len(r["runs_s"]) for r in recorded),
    }
    for timer in TIMERS:
        if timer not in rows[0]:
            continue
        values = [v for r in recorded for v in r[timer]]
        out[f"{timer}_median"] = round(statistics.median(values), 4)
        if plain:
            out[f"{timer}_plain_median"] = round(statistics.median(plain[0][timer]), 4)
    return out


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    session = Path(sys.argv[1])
    lines = (session / "runs.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    cells = {}
    for row in rows:
        cells.setdefault(row["cell"], []).append(row)
    summary = {name: cell_summary(cell_rows) for name, cell_rows in cells.items()}
    (session / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
