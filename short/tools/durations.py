#!/usr/bin/env python3
"""Writes every line's "duration" from the JSON-lines log as raw little-endian f64 (test 3's input).

usage: python3 tools/durations.py LOG.jsonl OUT.bin
"""
import json
import struct
import sys

def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    with open(sys.argv[1], "rb") as src, open(sys.argv[2], "wb") as out:
        for line in src:
            out.write(struct.pack("<d", float(json.loads(line)["duration"])))

if __name__ == "__main__":
    main()
