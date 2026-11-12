#!/usr/bin/env python3
"""Writes the records the sort and all-cores jobs read, so their programs load them without parsing JSON.

Per log line: f64 duration, u16 status, u64 bytes, u16 path length, path bytes (little endian, in log order).
Parsing JSON is what short/ measures; here both sides read the same simple binary file instead.

usage: python everyday/tools/records.py LOG.jsonl OUT.bin
"""
import json
import struct
import sys

HEAD = struct.Struct("<dHQH")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    n = 0
    with open(sys.argv[1], "rb") as src, open(sys.argv[2], "wb") as out:
        for line in src:
            if not line.strip():
                continue
            r = json.loads(line)
            path = r["path"].encode()
            if len(path) > 0xFFFF:
                raise ValueError(f"line {n + 1}: path longer than 65535 bytes")
            out.write(HEAD.pack(float(r["duration"]), int(r["status"]), int(r["bytes"]), len(path)))
            out.write(path)
            n += 1
    print(f"{n} records")


if __name__ == "__main__":
    main()
