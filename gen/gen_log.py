#!/usr/bin/env python3
"""Writes a deterministic JSON-lines web access log (same bytes on every machine for the same seed and count).

usage: python3 gen/gen_log.py OUT.jsonl [LINES=5000000] [SEED=20261031]
Prints the sha256 of the file so every machine can check it has the same input.
"""

import hashlib
import random
import sys

ROUTES = [
    ("/", False), ("/login", False), ("/logout", False), ("/search", False), ("/cart", False),
    ("/checkout", False), ("/health", False), ("/api/products", False), ("/api/categories", False),
    ("/api/products/{}", True), ("/api/products/{}/reviews", True), ("/api/users/{}", True),
    ("/api/users/{}/orders", True), ("/api/orders/{}", True), ("/api/orders/{}/items", True),
    ("/api/carts/{}", True), ("/static/img/{}.webp", True), ("/static/js/app.{}.js", True),
    ("/blog/{}", True), ("/api/sessions/{}", True),
]
ROUTE_WEIGHTS = [6, 2, 1, 5, 4, 2, 3, 6, 2, 14, 4, 8, 6, 7, 3, 5, 12, 2, 3, 5]
METHODS = ["GET", "GET", "GET", "GET", "POST", "PUT", "DELETE"]
STATUSES = [200] * 90 + [201] * 2 + [204, 301, 304, 304] + [404] * 3 + [500, 502, 503]
AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/19.0 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
    "Mozilla/5.0 (Linux; Android 16; Pixel 10) AppleWebKit/537.36 Chrome/141.0 Mobile Safari/537.36",
    "curl/8.15.0",
    "okhttp/5.1.0",
    "python-requests/2.33.1",
    "Go-http-client/2.0",
]
START_S = 1_793_404_800  # 2026-10-30T00:00:00Z


def iso(ms: int) -> str:
    s, milli = divmod(ms, 1000)
    day_s = s - START_S
    d, rem = divmod(day_s, 86400)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    return f"2026-10-{30 + d:02d}T{h:02d}:{m:02d}:{sec:02d}.{milli:03d}Z"


def main() -> None:
    out = sys.argv[1]
    lines = int(sys.argv[2]) if len(sys.argv) > 2 else 5_000_000
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 20261031
    if lines <= 0 or lines > 50_000_000:
        sys.exit("LINES must be between 1 and 50,000,000")
    rnd = random.Random(seed)
    ms = START_S * 1000
    sha = hashlib.sha256()
    step = max(1, 150_000_000 // lines)  # spread the lines over less than two days
    with open(out, "w", encoding="ascii", newline="\n") as f:
        buf = []
        for i in range(lines):
            ms += rnd.randint(0, 2 * step)
            tpl, has_id = rnd.choices(ROUTES, ROUTE_WEIGHTS)[0]
            path = tpl.format(min(int(rnd.paretovariate(0.9)), 200_000)) if has_id else tpl
            status = rnd.choice(STATUSES)
            size = 0 if status in (204, 304) else int(rnd.lognormvariate(8.0, 1.3))
            dur = round(rnd.lognormvariate(-4.0, 1.0), 4)
            ip = f"10.{rnd.randint(0, 255)}.{rnd.randint(0, 255)}.{rnd.randint(1, 254)}"
            buf.append(
                f'{{"ts":"{iso(ms)}","ip":"{ip}","method":"{rnd.choice(METHODS)}","path":"{path}",'
                f'"status":{status},"bytes":{size},"duration":{dur!r},"ua":"{rnd.choice(AGENTS)}"}}\n'
            )
            if len(buf) == 50_000:
                chunk = "".join(buf)
                f.write(chunk)
                sha.update(chunk.encode("ascii"))
                buf = []
        chunk = "".join(buf)
        f.write(chunk)
        sha.update(chunk.encode("ascii"))
    print(sha.hexdigest())


if __name__ == "__main__":
    main()
