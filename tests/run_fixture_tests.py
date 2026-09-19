#!/usr/bin/env python3
"""Fixture-driven acceptance tests for release_audit.py.

Spins up a local HTTP server serving tests/fixture-site/ (a deliberately
broken site), runs every release_audit subcommand against it, and asserts
that each expected finding is present with the expected status — plus a few
absence assertions so the script neither over- nor under-reports.

Exit code 0 = all assertions pass; 1 = any failure (details on stdout).
"""

import json
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE_SRC = HERE / "fixture-site"
SCRIPT = HERE.parent / "scripts" / "release_audit.py"


def write_png(path: Path, w: int, h: int):
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    row = b"\x00" + b"\x40\x80\xc0" * w
    raw = row * h
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def render_fixture(tmp: Path, port: int) -> Path:
    site = tmp / "site"
    shutil.copytree(FIXTURE_SRC, site)
    for tpl in site.rglob("*.in"):
        target = tpl.with_suffix("")  # strip .in, keep prior extension
        target.write_text(tpl.read_text().replace("{port}", str(port)))
        tpl.unlink()
    write_png(site / "assets" / "og-small.png", 100, 50)
    return site


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(port: int, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/index.html", timeout=1).read()
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("fixture server did not come up")


def run_audit(args):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True, text=True, timeout=120)
    return proc


# (description, [audit args], expectations)
# expectation: (finding_id, status_or_None) — None asserts the finding is absent
EXPECTED = [
    ("headers / production context", ["headers", "URL", "--context", "production"], [
        ("HTTP-001", "warn"),          # no TLS; loopback target caps at warn (deferred to deploy URL)
        ("SEC-001", "fail"),           # CSP missing
        ("SEC-002", "fail"),           # X-Content-Type-Options missing
        ("SEC-003", "fail"),           # X-Frame-Options missing
        ("SEC-004", "fail"),           # Referrer-Policy missing
        ("SEC-005", "fail"),           # Permissions-Policy missing
        ("SEC-006", None),             # HSTS not applicable over http
        ("PERF-002", "warn"),          # no compression
        ("PERF-003", "info"),          # no Cache-Control
        ("MIXED-001", None),           # not applicable over http
        ("JS-001", None),              # index has enough text
        ("NET-001", None),
    ]),
    ("headers / preview context downgrades", ["headers", "URL", "--context", "preview"], [
        ("HTTP-001", "warn"),          # TLS miss downgraded to warn
        ("SEC-001", "warn"),
    ]),
    ("meta / homepage with empty head", ["meta", "URL"], [
        ("SEO-001", "fail"),           # no title
        ("SEO-002", None),             # no title -> no length check
        ("SEO-003", "fail"),           # no description
        ("SEO-005", "warn"),           # no canonical
        ("SEO-010", None),             # indexable
        ("SOC-001", "warn"),           # no OG at all
        ("SOC-002", None),             # SOC-001 covers full absence
        ("SEO-006", None),             # exactly one h1
        ("SEO-007", None),
        ("SEO-008", None),             # no JSON-LD present (SEO-009 instead)
        ("SEO-009", "info"),
        ("PWA-001", "warn"),           # no favicon
        ("PWA-002", "info"),           # no manifest
        ("A11Y-001", "warn"),          # no lang
        ("BASE-001", None),            # charset present
        ("BASE-002", None),            # viewport present
        ("JS-001", None),
    ]),
    ("meta / post with long title, dup h1, broken JSON-LD, small og:image",
     ["meta", "URL"], [
        ("SEO-001", None),
        ("SEO-002", "warn"),           # title > 60
        ("SEO-003", None),
        ("SEO-004", "warn"),           # description < 50
        ("SEO-005", None),             # canonical present
        ("SOC-001", None),             # OG partial, not absent
        ("SOC-002", None),             # og:image present
        ("SOC-003", "warn"),           # 100x50 too small
        ("SEO-006", None),
        ("SEO-007", "warn"),           # two h1
        ("SEO-008", "fail"),           # broken JSON-LD
        ("A11Y-001", None),            # lang present
    ]),
    ("meta / spa shell becomes review, not fail", ["meta", "URL"], [
        ("JS-001", "review"),
        ("SEO-003", "review"),         # downgraded from fail
        ("SEO-001", None),
    ]),
    ("meta / noindex page", ["meta", "URL2"], [
        ("SEO-010", "fail"),
    ]),
    ("discovery / robots+sitemap cross-checks", ["discovery", "URL"], [
        ("DIS-001", None),             # robots.txt exists
        ("DIS-006", None),             # sitemap directive present
        ("DIS-000", "pass"),           # sitemap valid, 5 URLs
        ("DIS-003", "fail"),           # /missing.html 404s
        ("DIS-004", "warn"),           # /noindex.html in sitemap
        ("DIS-005", "warn"),           # /private/ blocked by robots yet in sitemap
        ("DIS-007", "info"),           # AI crawler summary
        ("DIS-008", None),
        ("GEO-001", "warn"),           # no llms.txt
        ("GEO-002", None),
    ]),
    ("links / finds dead page", ["links", "URL", "--max-pages", "20"], [
        ("LNK-001", "fail"),           # /missing.html
        ("LNK-003", None),
        ("LNK-SUM", "info"),
    ]),
    ("secrets / dist artifacts", ["secrets", "DIST"], [
        ("SEC-M-001", "fail"),         # app.js.map
        ("SEC-M-002", "fail"),         # .env
        ("SEC-M-003", "fail"),         # private key
        ("SEC-M-004", "fail"),         # AKIA...EXAMPLE
        ("SEC-M-005", "warn"),         # config.json api_key
    ]),
    ("privacy / shop page links policy+terms and fires trackers", ["privacy", "URL"], [
        ("PRV-001", "pass"),           # footer link to /privacy.html
        ("PRV-002", "pass"),           # footer link to /terms.html
        ("PRV-003", "pass"),           # policy page 200
        ("PRV-004", "pass"),           # terms page 200
        ("PRV-005", "pass"),           # keyword floor met
        ("PRV-010", "review"),         # googletagmanager + hotjar in static HTML
        ("PRV-011", None),             # mutually exclusive with PRV-010
        ("PRV-SUM", "info"),
    ]),
    ("privacy / bare index page has no policy, terms or trackers", ["privacy", "URL"], [
        ("PRV-001", "warn"),           # no links; common-path probes 404
        ("PRV-002", "warn"),
        ("PRV-003", None),
        ("PRV-004", None),
        ("PRV-005", None),
        ("PRV-010", None),
        ("PRV-011", "pass"),           # no scripts at all; not an SPA shell
    ]),
]


def main():
    port = free_port()
    tmp = Path(tempfile.mkdtemp(prefix="release-audit-fixture-"))
    site = render_fixture(tmp, port)
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
         "--directory", str(site)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/index.html"
    url_index = url
    url_post = f"http://127.0.0.1:{port}/blog/post.html"
    url_spa = f"http://127.0.0.1:{port}/spa.html"
    url_noindex = f"http://127.0.0.1:{port}/noindex.html"
    url_shop = f"http://127.0.0.1:{port}/shop.html"

    # meta expectations are evaluated against different fixture pages
    PAGE_FOR = {"meta / homepage with empty head": url_index,
                "meta / post with long title, dup h1, broken JSON-LD, small og:image": url_post,
                "meta / spa shell becomes review, not fail": url_spa,
                "meta / noindex page": url_noindex,
                "privacy / shop page links policy+terms and fires trackers": url_shop}

    passed = failed = 0
    try:
        wait_ready(port)
        for desc, args, expectations in EXPECTED:
            target = PAGE_FOR.get(desc, url_index)
            real_args = []
            for a in args:
                if a == "URL":
                    real_args.append(target)
                elif a == "URL2":
                    real_args.append(url_noindex)
                elif a == "DIST":
                    real_args.append(str(site / "dist"))
                else:
                    real_args.append(a)
            proc = run_audit(real_args)
            if proc.returncode not in (0, 1):
                print(f"FAIL  {desc}: exit={proc.returncode}\n{proc.stderr[-800:]}")
                failed += 1
                continue
            try:
                report = json.loads(proc.stdout)
            except json.JSONDecodeError:
                print(f"FAIL  {desc}: stdout is not valid JSON:\n{proc.stdout[-400:]}")
                failed += 1
                continue
            by_id = {f["id"]: f for f in report["findings"]}
            for fid, want in expectations:
                got = by_id.get(fid, {}).get("status")
                if want is None:
                    if got is None:
                        passed += 1
                    else:
                        print(f"FAIL  {desc}: {fid} present with status '{got}', expected absent"
                              f" ({by_id.get(fid, {}).get('message', '')})")
                        failed += 1
                elif got == want:
                    passed += 1
                else:
                    print(f"FAIL  {desc}: {fid} status '{got}', expected '{want}'"
                            f" ({by_id.get(fid, {}).get('message', '')})")
                    failed += 1
            print(f"ran   {desc}: {report['summary']}")

        # gate behaviour: headers on production fixture has fails -> exit 1
        proc = run_audit(["headers", url, "--context", "production", "--gate"])
        if proc.returncode == 1:
            print("ran   gate: --gate exits 1 when fails present")
            passed += 1
        else:
            print(f"FAIL  gate: expected exit 1, got {proc.returncode}")
            failed += 1

        # redaction: the full fake AWS key must never appear in output
        proc = run_audit(["secrets", str(site / "dist")])
        if "AKIAIOSFODNN7EXAMPLE" not in proc.stdout:
            print("ran   redaction: full secret value not echoed")
            passed += 1
        else:
            print("FAIL  redaction: full secret leaked into output")
            failed += 1

        # markdown format smoke
        proc = run_audit(["headers", url, "--format", "md"])
        if proc.returncode in (0, 1) and "| ID |" in proc.stdout:
            print("ran   md format: table rendered")
            passed += 1
        else:
            print("FAIL  md format")
            failed += 1

    finally:
        server.terminate()
        server.wait(timeout=5)
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'PASS' if failed == 0 else 'FAIL'}: {passed} assertions passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
