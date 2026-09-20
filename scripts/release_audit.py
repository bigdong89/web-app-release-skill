#!/usr/bin/env python3
"""Deterministic pre-release checks for web apps and sites.

Subcommands:
  headers <url>    TLS, redirects, security headers, cookies, compression, mixed content
  meta <url>       title/description/canonical/OG/H1/JSON-LD/favicon/viewport/lang
  discovery <url>  robots.txt, sitemap.xml validity + cross-checks, llms.txt
  links <url>      same-origin crawl for broken links and redirect chains
  secrets <dir>    source maps, .env files, credential patterns in a build output dir
  privacy <url>    privacy/terms link discovery, page reachability, third-party trackers in static HTML
  security <url>   sensitive-path exposure, SRI, CSP quality, CORS, 404 debug leak, TLS diagnosis

Output: JSON (default) or Markdown (--format md). With --gate the exit code is 1
when any finding has status "fail" (CI-friendly).

Statuses: pass / warn / fail / info / review. "review" means the check needs a
real browser or human judgment (e.g. client-rendered SPA shell) and must NOT be
reported as a failure without browser verification.

Judgment-only domains (content quality, UX, legal adequacy) are deliberately
not covered here — see references/domains.md of the web-app-release-skill.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import http.client
import json
import re
import socket
import sys
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

VERSION = 1
UA = "release-audit-script/1.0 (pre-release checker; respects robots.txt)"

# ---------------------------------------------------------------------------
# Thresholds. Defaults reflect public standards (see references/domains.md for
# sources and dates). Callers may override via .release-check.yml handled by the
# agent before invoking this script — the script itself takes CLI args only.
# ---------------------------------------------------------------------------
TH = {
    "title_min": 10,
    "title_max": 60,
    "desc_min": 50,
    "desc_max": 160,
    "og_image_min_width": 600,      # recommended 1200x630; below 600 wide is a hard warn
    "og_ratio_min": 1.4,            # 1200/630 ≈ 1.91; lenient band
    "og_ratio_max": 2.3,
    "redirect_report_hops": 3,      # more hops than this -> info
    "max_body_bytes": 3_000_000,
    "max_file_bytes": 5_000_000,    # secrets scan per-file cap
    "links_max_pages": 50,
    "links_delay": 0.25,
    "links_timeout": 10,
    "sitemap_sample": 10,           # URLs fetched for status/noindex sampling
    "sitemap_cap": 1000,
}

# Platforms that do not let users set arbitrary response headers on their
# *.subdomain (custom domains usually can). Missing headers there -> warn.
HOST_LIMITED_SUFFIXES = ("github.io", "gitlab.io", "github-preview.io")

# AI crawlers worth summarizing (as of 2026-09; see references/domains.md).
AI_CRAWLERS = [
    "GPTBot", "OAI-SearchBot", "ChatGPT-User",
    "ClaudeBot", "Claude-User", "Claude-SearchBot",
    "PerplexityBot", "Perplexity-User",
    "Google-Extended", "Applebot-Extended",
    "Bytespider", "CCBot", "Amazonbot", "Meta-ExternalAgent",
]

SECURITY_HEADERS = [
    ("content-security-policy", "SEC-001"),
    ("x-content-type-options", "SEC-002"),
    ("x-frame-options", "SEC-003"),
    ("referrer-policy", "SEC-004"),
    ("permissions-policy", "SEC-005"),
]

SECURITY_HEADER_FIX = {
    "SEC-001": "Add a Content-Security-Policy (start with report-only, tighten iteratively).",
    "SEC-002": "Send X-Content-Type-Options: nosniff.",
    "SEC-003": "Send X-Frame-Options: DENY/SAMEORIGIN or CSP frame-ancestors.",
    "SEC-004": "Send Referrer-Policy (strict-origin-when-cross-origin is a sane default).",
    "SEC-005": "Send a Permissions-Policy restricting camera/microphone/geolocation.",
    "SEC-006": "Send Strict-Transport-Security once HTTPS is enforced (e.g. max-age=31536000).",
}

SECRET_PATTERNS = [
    ("SEC-M-003", "private key block",
     re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("SEC-M-004", "AWS access key id",
     re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("SEC-M-004", "Google API key",
     re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("SEC-M-004", "Slack token",
     re.compile(r"\bxox[abprs]-[0-9A-Za-z\-]{10,}")),
]
GENERIC_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password)\b['\"]?\s*[:=]\s*['\"][^'\"]{12,}['\"]")
GENERIC_SECRET_EXTS = {".json", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".xml", ".txt"}

# Third-party analytics/ads/marketing hosts for the privacy check (compiled
# 2026-09). Suffix match against script/iframe src hostnames. Static-HTML floor
# only — JS-injected trackers need the browser layer.
KNOWN_TRACKER_HOSTS = [
    "googletagmanager.com", "google-analytics.com", "analytics.google.com",
    "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "facebook.net", "hotjar.com", "clarity.ms", "mixpanel.com",
    "segment.io", "segment.com", "amplitude.com", "fullstory.com",
    "posthog.com", "plausible.io", "matomo.cloud", "heapanalytics.com",
    "chartbeat.com", "criteo.com", "criteo.net", "taboola.com", "outbrain.com",
    "ads-twitter.com", "licdn.com", "sc-static.net", "analytics.tiktok.com",
    "hs-scripts.com", "intercom.io", "omtrdc.net", "quantserve.com",
    "scorecardresearch.com", "cloudflareinsights.com", "mc.yandex.ru",
    "hm.baidu.com",
]

# Link-discovery vocabulary. Tokens match whole path segments (so "photos"
# never matches "tos"); substrings cover hyphenated compounds and CJK.
PRIVACY_LINK_TOKENS = ("privacy", "datenschutz", "confidentiality")
PRIVACY_LINK_SUBSTRINGS = ("data-protection", "隐私")
TERMS_LINK_TOKENS = ("terms", "tos", "agb", "conditions", "agreement")
TERMS_LINK_SUBSTRINGS = ("服务条款", "条款")
PRIVACY_PAGE_KEYWORDS = ("personal data", "personenbezogen", "data protection",
                         "gdpr", "dsgvo", "cookie", "隐私", "个人信息")
PRIVACY_PATH_PROBES = ("/privacy", "/privacy-policy", "/privacy_policy",
                       "/legal/privacy", "/datenschutz")
TERMS_PATH_PROBES = ("/terms", "/terms-of-service", "/terms_of_service",
                     "/legal/terms", "/agb")

# Paths that must never be publicly served (compiled 2026-09 from common
# deployment-leak reports). Probed with GET only — read-only, no exploitation.
SECURITY_PROBE_PATHS = [
    ("/.env", "dotenv file"),
    ("/.git/HEAD", "git repository metadata"),
    ("/.DS_Store", "macOS resource fork"),
    ("/.svn/entries", "svn repository metadata"),
    ("/backup.zip", "backup archive"),
    ("/dump.sql", "SQL dump"),
    ("/db.sqlite3", "SQLite database"),
    ("/server-status", "Apache status endpoint"),
    ("/debug/vars", "Go expvar endpoint"),
    ("/actuator/env", "Spring Boot actuator"),
    ("/.aws/credentials", "AWS credentials file"),
]
DEBUG_LEAK_SIGNATURES = [
    "Traceback (most recent call last)",
    "DEBUG = True",
    "Whoops, looks like something went wrong",
    "Stack trace:",
    "at org.springframework",
    "Warning: Undefined",
]
TLS_ERROR_SIGNATURES = ("CERTIFICATE_VERIFY_FAILED", "SSL", "certificate")

# Dangerous sinks in shipped JS — warn-level evidence hooks; exploitability is
# the agent's judgment (bundled polyfills sometimes legitimately contain eval).
DANGEROUS_API_PATTERNS = [
    ("SEC-M-006", "innerHTML assignment", re.compile(r"\.innerHTML\s*=")),
    ("SEC-M-006", "dangerouslySetInnerHTML", re.compile(r"dangerouslySetInnerHTML")),
    ("SEC-M-006", "document.write", re.compile(r"document\.write\s*\(")),
    ("SEC-M-006", "eval call", re.compile(r"\beval\s*\(")),
    ("SEC-M-006", "new Function", re.compile(r"new\s+Function\s*\(")),
    ("SEC-M-006", "v-html directive", re.compile(r"\bv-html\b")),
]
WILDCARD_POSTMESSAGE_RE = re.compile(r"postMessage\([^;]{0,200}?,\s*['\"]\*['\"]")
DANGEROUS_API_EXTS = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".html"}


def finding(fid, status, message, evidence="", fix=""):
    return {"id": fid, "status": status, "message": message,
            "evidence": evidence[:400], "fix": fix[:400]}


# ---------------------------------------------------------------------------
# HTTP fetching with manual redirect-chain tracking
# ---------------------------------------------------------------------------
@dataclass
class FetchResult:
    status: int = 0
    headers: object = None
    raw: bytes = b""
    url: str = ""
    chain: list = None
    error: str = ""
    too_many_redirects: bool = False

    def __post_init__(self):
        if self.chain is None:
            self.chain = []


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # noqa: ARG002 - force manual redirect handling


_OPENER = build_opener(_NoRedirect)


def fetch(url, headers=None, timeout=15, max_redirects=5):
    extra = {"User-Agent": UA}
    extra.update(headers or {})
    chain = [url]
    cur = url
    status, resp_headers, raw = 0, None, b""
    for _ in range(max_redirects + 1):
        req = Request(cur, headers=extra)
        try:
            resp = _OPENER.open(req, timeout=timeout)
            status, resp_headers, raw = resp.status, resp.headers, resp.read(TH["max_body_bytes"] + 1)
        except HTTPError as e:
            status, resp_headers, raw = e.code, e.headers, e.read(TH["max_body_bytes"] + 1) or b""
        except (URLError, socket.timeout, ConnectionError, OSError, ValueError,
                http.client.HTTPException) as e:
            return FetchResult(error=str(e), chain=chain)
        if 300 <= status < 400:
            loc = resp_headers.get("Location") if resp_headers is not None else None
            if not loc:
                break
            cur = urljoin(cur, loc)
            chain.append(cur)
            continue
        break
    return FetchResult(status=status, headers=resp_headers, raw=raw,
                       url=cur, chain=chain,
                       too_many_redirects=(300 <= status < 400))


def decode_body(res):
    """Return (text, note). text is None when the body cannot be decoded."""
    if res.raw is None or res.raw == b"":
        return "", None
    enc = (res.headers.get("Content-Encoding") if res.headers else "") or ""
    enc = enc.strip().lower()
    data = res.raw
    if enc in ("gzip", "x-gzip"):
        try:
            data = gzip.decompress(res.raw)
        except Exception:
            return None, "gzip-decode-failed"
    elif enc == "deflate":
        try:
            data = zlib.decompress(res.raw)
        except Exception:
            try:
                data = zlib.decompress(res.raw, -zlib.MAX_WBITS)
            except Exception:
                return None, "deflate-decode-failed"
    elif enc in ("br", "zstd"):
        return None, f"{enc}-unsupported-decode"
    charset = "utf-8"
    ctype = (res.headers.get("Content-Type") if res.headers else "") or ""
    m = re.search(r"charset=([^\s;]+)", ctype, re.I)
    if m:
        charset = m.group(1).strip("\"'")
    try:
        return data.decode(charset, "replace"), None
    except (LookupError, UnicodeDecodeError):
        return data.decode("utf-8", "replace"), None


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------
class PageParser(HTMLParser):
    """Collects everything the audit needs from one HTML document."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self.metas = []          # (key, value, content) key=name|property|http-equiv
        self.link_rels = []      # (rel_lower, href)
        self.h1 = 0
        self.a_hrefs = []
        self.res_srcs = []       # img/script/iframe/source/video src, link href
        self.script_srcs = []    # <script src> and <iframe src> — tracker detection scans both
        self.ext_resources = []  # (tag, absolute-url, has_integrity) for SRI checks
        self.jsonld = []
        self.robots_meta = ""
        self.lang = ""
        self.text_chars = 0
        self.script_count = 0
        self._ld_buf = None
        self._skip_depth = 0     # inside <script> or <style> (non-ld+json)

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "meta":
            key = a.get("name") or a.get("property") or a.get("http-equiv") or ""
            self.metas.append((key.lower(), a.get("content", ""), a))
        elif tag == "link":
            rel = a.get("rel", "").lower()
            self.link_rels.append((rel, a.get("href", "")))
            self.res_srcs.append(a.get("href", ""))
            href = a.get("href", "")
            if "stylesheet" in rel and href.startswith(("http://", "https://")):
                self.ext_resources.append(("link", href, "integrity" in a))
        elif tag == "title":
            self._in_title = True
        elif tag == "h1":
            self.h1 += 1
        elif tag == "a":
            self.a_hrefs.append(a.get("href", ""))
        elif tag in ("img", "script", "iframe", "source", "video"):
            if tag == "script":
                self.script_count += 1
                t = a.get("type", "").lower()
                if "ld+json" in t:
                    self._ld_buf = []
                    return
            self.res_srcs.append(a.get("src", ""))
            if tag in ("script", "iframe"):
                self.script_srcs.append(a.get("src", ""))
            src = a.get("src", "")
            if tag == "script" and src.startswith(("http://", "https://")):
                self.ext_resources.append(("script", src, "integrity" in a))
        if tag in ("script", "style") and self._ld_buf is None:
            self._skip_depth += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() in ("script", "style") and self._ld_buf is None:
            self._skip_depth = max(0, self._skip_depth - 1)
        if tag.lower() == "script" and self._ld_buf is not None:
            self._flush_ld()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            if self._ld_buf is not None:
                self._flush_ld()
            else:
                self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "style":
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data):
        if self._ld_buf is not None:
            self._ld_buf.append(data)
        elif self._in_title:
            self.title += data
        elif self._skip_depth == 0:
            self.text_chars += len(data.strip())

    def _flush_ld(self):
        if self._ld_buf is not None:
            self.jsonld.append("".join(self._ld_buf).strip())
            self._ld_buf = None

    def meta_content(self, key):
        for k, content, _ in self.metas:
            if k == key:
                return content
        return None

    def has_robots_noindex(self):
        for k, content, _ in self.metas:
            if k == "robots" and "noindex" in (content or "").lower():
                return True
        return False

    def is_spa_shell(self):
        return self.text_chars < 200 and self.script_count >= 1


def parse_page(html_text):
    p = PageParser()
    try:
        p.feed(html_text)
        p.close()
    except Exception:
        pass  # best-effort; lenient parsers keep the audit running
    return p


# ---------------------------------------------------------------------------
# Image dimension sniffing (PNG / GIF / JPEG; WebP & others -> unverified)
# ---------------------------------------------------------------------------
def image_dimensions(raw):
    if len(raw) >= 24 and raw[:8] == b"\x89PNG\r\n\x1a\n":
        w = int.from_bytes(raw[16:20], "big")
        h = int.from_bytes(raw[20:24], "big")
        return w, h
    if len(raw) >= 10 and raw[:4] == b"GIF8":
        w = int.from_bytes(raw[6:8], "little")
        h = int.from_bytes(raw[8:10], "little")
        return w, h
    if len(raw) >= 4 and raw[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(raw):
            if raw[i] != 0xFF:
                i += 1
                continue
            marker = raw[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h = int.from_bytes(raw[i + 5:i + 7], "big")
                w = int.from_bytes(raw[i + 7:i + 9], "big")
                return w, h
            seg = int.from_bytes(raw[i + 2:i + 4], "big")
            i += 2 + seg
        return None
    return None


# ---------------------------------------------------------------------------
# robots.txt parsing (minimal but with longest-match allow/disallow)
# ---------------------------------------------------------------------------
def parse_robots(text):
    groups = {}
    sitemaps = []
    order = []
    last_ua = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip().lower()
        val = val.strip()
        if key == "user-agent":
            ua = val.lower()
            if ua not in groups:
                groups[ua] = {"allow": [], "disallow": []}
                order.append(ua)
            last_ua = ua
        elif key in ("allow", "disallow") and last_ua is not None:
            groups[last_ua][key].append(val)
        elif key == "sitemap" and val:
            sitemaps.append(val)
    return {"groups": groups, "order": order, "sitemaps": sitemaps}


def robots_group_allowed(robots, path):
    group = None
    for ua in robots["order"]:
        if ua != "*":
            group = robots["groups"][ua]
            break
    if group is None:
        group = robots["groups"].get("*")
    if group is None:
        return True
    best_len, allowed = -1, True
    for p in group["disallow"]:
        if p and path.startswith(p) and len(p) > best_len:
            best_len, allowed = len(p), False
    for p in group["allow"]:
        if path.startswith(p) and len(p) > best_len:
            best_len, allowed = len(p), True
    return allowed if best_len >= 0 else True


# ---------------------------------------------------------------------------
# Report assembly and formatting
# ---------------------------------------------------------------------------
def assemble(target, context, findings, started):
    counts = {s: sum(1 for f in findings if f["status"] == s)
              for s in ("pass", "warn", "fail", "info", "review")}
    gate = "fail" if counts["fail"] else "pass"
    return {
        "tool": "release_audit", "version": VERSION, "target": target,
        "context": context,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_s": round(time.time() - started, 2),
        "summary": {**counts, "gate": gate},
        "findings": findings,
    }


def to_markdown(report, subcmd):
    s = report["summary"]
    lines = [
        f"# release_audit — {subcmd} {report['target']}",
        f"context: {report['context']} · duration: {report['duration_s']}s · "
        f"pass {s['pass']} · warn {s['warn']} · fail {s['fail']} · "
        f"info {s['info']} · review {s['review']} · GATE={s['gate'].upper()}",
        "",
        "| ID | Status | Message | Evidence / Fix |",
        "|---|---|---|---|",
    ]
    for f in report["findings"]:
        ev = (f["evidence"] + (" · FIX: " + f["fix"] if f["fix"] else "")).replace("|", "\\|")
        lines.append(f"| {f['id']} | {f['status']} | {f['message'].replace('|', '\\|')} | {ev or '—'} |")
    return "\n".join(lines) + "\n"


def output_and_exit(report, args, subcmd):
    if args.format == "md":
        sys.stdout.write(to_markdown(report, subcmd))
    else:
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    if args.gate and report["summary"]["gate"] == "fail":
        sys.exit(1)
    sys.exit(0)


def add_common_args(p):
    p.add_argument("--context", choices=["production", "preview"], default="production",
                   help="preview downgrades TLS/header misses from fail to warn")
    p.add_argument("--header", action="append", default=[],
                   help="extra request header 'Name: value' (repeatable)")
    p.add_argument("--cookie", default="", help="Cookie header value for authed pages")
    p.add_argument("--timeout", type=int, default=15)
    p.add_argument("--format", choices=["json", "md"], default="json")
    p.add_argument("--gate", action="store_true", help="exit 1 when any check fails")


def request_headers(args):
    headers = {}
    for h in args.header:
        if ":" in h:
            k, v = h.split(":", 1)
            headers[k.strip()] = v.strip()
    if args.cookie:
        headers["Cookie"] = args.cookie
    return headers


def ctx_status(args, production_status):
    """preview downgrades fail -> warn."""
    if production_status == "fail" and args.context == "preview":
        return "warn"
    return production_status


def host_limited(url):
    netloc = urlsplit(url).netloc.lower()
    return any(netloc == s or netloc.endswith("." + s) for s in HOST_LIMITED_SUFFIXES)


def is_private_target(url):
    """Loopback / private-network hosts: TLS verdicts are deferred to the
    deployed URL, because localhost can never satisfy them."""
    host = (urlsplit(url).hostname or "").lower().strip("[]")
    if not host:
        return False
    if host in ("localhost", "::1") or host.startswith("127."):
        return True
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)\.(\d+)$", host)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return a == 10 or (a == 192 and b == 168) or (a == 172 and 16 <= b <= 31)
    return host.endswith(".local") or host.endswith(".internal")


def downgrade_for_host(status, url):
    return "warn" if (status == "fail" and host_limited(url)) else status


# ---------------------------------------------------------------------------
# Subcommand: headers
# ---------------------------------------------------------------------------
def cmd_headers(args):
    started = time.time()
    url = args.url
    res = fetch(url, request_headers(args), args.timeout)
    out = []
    if res.error:
        out.append(finding("NET-001", "fail", "Target unreachable",
                           evidence=f"{url} -> {res.error}",
                           fix="Check DNS, TLS certificate, and firewall before release."))
        return assemble(url, args.context, out, started)

    hops = len(res.chain) - 1
    final = res.url or url
    final_scheme = urlsplit(final).scheme

    out.append(finding("REDIR-001" if hops > TH["redirect_report_hops"] else "REDIR-000",
                       "info" if hops > TH["redirect_report_hops"] else "pass",
                       f"Redirect chain: {hops} hop(s)",
                       evidence=" -> ".join(res.chain)))
    if hops > TH["redirect_report_hops"]:
        out[-1]["fix"] = "Shorten redirect chains; every hop adds latency."

    if final_scheme != "https":
        st = ctx_status(args, "fail")
        ev = f"final URL scheme: {final_scheme}"
        if st == "fail" and is_private_target(final):
            st = "warn"
            ev += " (loopback/private target — TLS verdict deferred to the deployed URL)"
        out.append(finding("HTTP-001", st, "Site is not served over HTTPS",
                           evidence=ev,
                           fix="Serve everything over HTTPS and 301-redirect HTTP."))
    elif url.startswith("http://"):
        out.append(finding("HTTP-002", "pass", "HTTP redirects to HTTPS",
                           evidence=" -> ".join(res.chain)))

    hdr = res.headers
    for name, fid in SECURITY_HEADERS:
        val = hdr.get(name) if hdr else None
        if name == "x-frame-options" and not val and hdr and "frame-ancestors" in (hdr.get("content-security-policy") or "").lower():
            val = "(covered by CSP frame-ancestors)"
        if not val:
            out.append(finding(fid, downgrade_for_host(ctx_status(args, "fail"), final),
                               f"Missing security header: {name}",
                               fix=SECURITY_HEADER_FIX[fid]))
        elif name == "x-content-type-options" and "nosniff" not in val.lower():
            out.append(finding(fid, "warn", f"X-Content-Type-Options should be 'nosniff'",
                               evidence=f"got: {val}"))
        else:
            out.append(finding(fid, "pass", f"{name}: {val[:80]}"))

    if final_scheme == "https":
        hsts = hdr.get("strict-transport-security") if hdr else None
        if not hsts:
            out.append(finding("SEC-006", downgrade_for_host(ctx_status(args, "fail"), final),
                               "Missing HSTS header",
                               fix=SECURITY_HEADER_FIX["SEC-006"]))
        else:
            out.append(finding("SEC-006", "pass", f"strict-transport-security: {hsts[:80]}"))

    set_cookies = hdr.get_all("Set-Cookie") if hdr else None
    if set_cookies:
        problems = []
        for ck in set_cookies:
            name = ck.split("=", 1)[0]
            missing = [f for f in ("Secure", "HttpOnly") if f.lower() not in ck.lower()]
            if "samesite" not in ck.lower():
                missing.append("SameSite")
            if missing:
                problems.append(f"{name}: missing {', '.join(missing)}")
        if problems:
            out.append(finding("SEC-007", "warn", "Cookies without recommended flags",
                               evidence="; ".join(problems[:5]),
                               fix="Set Secure; HttpOnly; SameSite on session cookies."))

    cenc = (hdr.get("Content-Encoding") if hdr else "") or ""
    if cenc.strip().lower() in ("gzip", "x-gzip", "deflate", "br", "zstd"):
        out.append(finding("COMP-001", "pass", f"Content-Encoding: {cenc}"))
    else:
        out.append(finding("PERF-002", "warn", "Response is not compressed",
                           fix="Enable gzip/brotli at the server or CDN."))

    if not (hdr.get("Cache-Control") if hdr else None):
        out.append(finding("PERF-003", "info", "No Cache-Control header on the HTML document",
                           fix="Set sane cache policy: HTML no-cache; assets immutable."))

    text, note = decode_body(res)
    if note:
        out.append(finding("BODY-001", "review", f"Body not decoded ({note}); content checks skipped"))
    else:
        page = parse_page(text)
        if final_scheme == "https":
            mixed = [s for s in page.res_srcs + page.a_hrefs if s.lower().startswith("http://")]
            if mixed:
                out.append(finding("MIXED-001", "fail", "Mixed content: http:// resources on an HTTPS page",
                                   evidence="; ".join(mixed[:5]),
                                   fix="Load all subresources over HTTPS."))
        if page.is_spa_shell():
            out.append(finding("JS-001", "review",
                               "Page looks like a client-rendered SPA shell; verify rendered content in a browser"))
    return assemble(url, args.context, out, started)


# ---------------------------------------------------------------------------
# Subcommand: meta
# ---------------------------------------------------------------------------
def cmd_meta(args):
    started = time.time()
    url = args.url
    res = fetch(url, request_headers(args), args.timeout)
    out = []
    if res.error:
        out.append(finding("NET-001", "fail", "Target unreachable",
                           evidence=f"{url} -> {res.error}"))
        return assemble(url, args.context, out, started)

    text, note = decode_body(res)
    if note:
        out.append(finding("BODY-001", "review", f"Body not decoded ({note}); meta checks need a browser"))
        return assemble(url, args.context, out, started)

    page = parse_page(text)
    if page.is_spa_shell():
        out.append(finding("JS-001", "review",
                           "Client-rendered SPA shell detected; head tags may be injected at runtime — "
                           "verify title/description/OG in a browser before judging"))
        out.append(finding("SEO-003", "review", "meta description not verifiable in static HTML (SPA shell)"))
        return assemble(url, args.context, out, started)

    title = page.title.strip()
    if not title:
        out.append(finding("SEO-001", ctx_status(args, "fail"), "Missing <title>"))
    elif not (TH["title_min"] <= len(title) <= TH["title_max"]):
        out.append(finding("SEO-002", "warn", f"Title length {len(title)} outside {TH['title_min']}-{TH['title_max']}",
                           evidence=title))

    desc = page.meta_content("description")
    if desc is None or not desc.strip():
        out.append(finding("SEO-003", ctx_status(args, "fail"), "Missing meta description"))
    elif not (TH["desc_min"] <= len(desc.strip()) <= TH["desc_max"]):
        out.append(finding("SEO-004", "warn", f"Description length {len(desc.strip())} outside {TH['desc_min']}-{TH['desc_max']}",
                           evidence=desc.strip()))

    canonical = next((href for rel, href in page.link_rels if "canonical" in rel), None)
    if not canonical:
        out.append(finding("SEO-005", "warn", "Missing rel=canonical",
                           fix="Add <link rel=canonical> pointing at the final URL."))

    if page.has_robots_noindex():
        out.append(finding("SEO-010", ctx_status(args, "fail"),
                           "Page has meta robots noindex",
                           fix="Remove noindex unless the page must stay out of search."))

    og_title = page.meta_content("og:title")
    og_desc = page.meta_content("og:description")
    og_image = page.meta_content("og:image")
    if not og_title and not og_desc:
        out.append(finding("SOC-001", "warn", "No Open Graph tags (og:title/og:description)",
                           fix="Add OG tags so shared links render a card."))
    if og_title and not og_image:
        out.append(finding("SOC-002", "warn", "og:image missing while other OG tags present",
                           fix="Add a 1200x630 og:image."))
    if og_image:
        img = fetch(urljoin(res.url or url, og_image), request_headers(args), args.timeout)
        if img.error or img.status >= 400 or not img.raw:
            out.append(finding("SOC-003", "warn", "og:image could not be fetched",
                               evidence=f"{og_image} -> {img.error or img.status}"))
        else:
            dims = image_dimensions(img.raw)
            if dims is None:
                out.append(finding("SOC-003", "warn", "og:image format not verifiable (use PNG/JPEG/WebP)",
                                   evidence=og_image))
            elif (dims[0] < TH["og_image_min_width"]
                  or not (TH["og_ratio_min"] <= dims[0] / dims[1] <= TH["og_ratio_max"])):
                out.append(finding("SOC-003", "warn",
                                   f"og:image {dims[0]}x{dims[1]} far from recommended 1200x630",
                                   evidence=og_image))
            else:
                out.append(finding("SOC-003", "pass", f"og:image {dims[0]}x{dims[1]}"))

    if page.h1 == 0:
        out.append(finding("SEO-006", ctx_status(args, "fail"), "No <h1> on the page"))
    elif page.h1 > 1:
        out.append(finding("SEO-007", "warn", f"{page.h1} <h1> elements (recommend exactly one)"))

    if page.jsonld:
        bad = []
        for i, block in enumerate(page.jsonld):
            try:
                json.loads(block)
            except Exception as e:
                bad.append(f"block {i}: {e}")
        if bad:
            out.append(finding("SEO-008", ctx_status(args, "fail"), "Invalid JSON-LD structured data",
                               evidence="; ".join(bad[:3])))
        else:
            out.append(finding("SD-001", "pass", f"{len(page.jsonld)} valid JSON-LD block(s)"))
    else:
        out.append(finding("SEO-009", "info", "No structured data (JSON-LD) on the page"))

    if not any("icon" in rel for rel, _ in page.link_rels):
        out.append(finding("PWA-001", "warn", "No favicon/apple-touch-icon link"))
    if not any(rel == "manifest" for rel, _ in page.link_rels):
        out.append(finding("PWA-002", "info", "No web app manifest linked"))
    if not page.lang:
        out.append(finding("A11Y-001", "warn", "<html> lacks lang attribute"))
    if not page.meta_content("viewport"):
        out.append(finding("BASE-002", "warn", "Missing viewport meta tag"))
    if not any("charset" in a for (_k, _c, a) in page.metas) and "charset" not in (
            (res.headers.get("Content-Type") if res.headers else "") or "").lower():
        out.append(finding("BASE-001", "warn", "No charset declared (meta or Content-Type)"))
    return assemble(url, args.context, out, started)


# ---------------------------------------------------------------------------
# Subcommand: discovery
# ---------------------------------------------------------------------------
def cmd_discovery(args):
    started = time.time()
    url = args.url
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    req_h = request_headers(args)
    out = []

    robots_res = fetch(base + "/robots.txt", req_h, args.timeout)
    robots = None
    if robots_res.error or robots_res.status != 200 or not robots_res.raw.strip():
        out.append(finding("DIS-001", "warn", "No reachable robots.txt",
                           evidence=f"GET /robots.txt -> {robots_res.error or robots_res.status}",
                           fix="Add robots.txt with a Sitemap directive."))
    else:
        robots_text, _ = decode_body(robots_res)
        robots = parse_robots(robots_text or "")
        if not robots["sitemaps"]:
            out.append(finding("DIS-006", "info", "robots.txt has no Sitemap directive"))
        seen_ua = {ua for ua in robots["order"] if ua != "*"}
        ai_found = [ua for ua in AI_CRAWLERS if ua.lower() in seen_ua]
        out.append(finding("DIS-007", "info",
                           f"AI crawler rules: {len(ai_found)} of {len(AI_CRAWLERS)} known crawlers explicitly addressed"
                           + (f" ({', '.join(ai_found)})" if ai_found else ""),
                           fix="Decide intentionally which AI crawlers may access the site; see references/domains.md GEO section."))

    sitemap_url = (robots["sitemaps"][0] if robots and robots["sitemaps"] else base + "/sitemap.xml")
    sm_res = fetch(sitemap_url, req_h, args.timeout)
    locs = []
    if sm_res.error or sm_res.status != 200:
        out.append(finding("DIS-002", "warn", "No reachable sitemap.xml",
                           evidence=f"GET {sitemap_url} -> {sm_res.error or sm_res.status}",
                           fix="Publish sitemap.xml and reference it from robots.txt."))
    else:
        sm_text, _ = decode_body(sm_res)
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(sm_text)
            ns = ""
            if root.tag.startswith("{"):
                ns = root.tag.split("}")[0] + "}"
            locs = [(el.text or "").strip() for el in root.iter(ns + "loc")]
            locs = [u for u in locs if u][: TH["sitemap_cap"]]
            if not locs:
                out.append(finding("DIS-008", "fail", "sitemap.xml contains no <loc> entries"))
            else:
                out.append(finding("DIS-000", "pass", f"sitemap.xml valid, {len(locs)} URL(s)"))
        except ET.ParseError as e:
            out.append(finding("DIS-008", "fail", "sitemap.xml is not valid XML", evidence=str(e)))

    if locs and robots:
        blocked = [u for u in locs if not robots_group_allowed(robots, urlsplit(u).path or "/")]
        if blocked:
            out.append(finding("DIS-005", "warn",
                               "robots.txt disallows URL(s) that the sitemap lists (contradiction)",
                               evidence="; ".join(blocked[:5]),
                               fix="Remove them from the sitemap or unblock them in robots.txt."))
        sample = [u for u in locs if robots_group_allowed(robots, urlsplit(u).path or "/")][: TH["sitemap_sample"]]
        broken, noindex = [], []
        for u in sample:
            r = fetch(u, req_h, args.timeout)
            if r.error or r.status >= 400:
                broken.append(f"{u} -> {r.error or r.status}")
                continue
            t, n = decode_body(r)
            if t and not n and parse_page(t).has_robots_noindex():
                noindex.append(u)
            time.sleep(0.05)
        if broken:
            out.append(finding("DIS-003", ctx_status(args, "fail"),
                               "Sitemap lists URL(s) that return errors",
                               evidence="; ".join(broken[:5])))
        if noindex:
            out.append(finding("DIS-004", "warn", "Sitemap lists URL(s) carrying noindex",
                               evidence="; ".join(noindex[:5]),
                               fix="Remove noindex or drop the URL from the sitemap."))

    llms = fetch(base + "/llms.txt", req_h, args.timeout)
    if llms.error or llms.status != 200 or not llms.raw.strip():
        out.append(finding("GEO-001", "warn", "No llms.txt at site root",
                           evidence=f"GET /llms.txt -> {llms.error or llms.status}",
                           fix="Consider llms.txt: a short markdown overview linking key pages for AI crawlers."))
    else:
        out.append(finding("GEO-002", "pass", "llms.txt present"))

    sectxt = fetch(base + "/.well-known/security.txt", req_h, args.timeout)
    if sectxt.error or sectxt.status != 200 or not sectxt.raw.strip():
        out.append(finding("DIS-009", "info", "No security.txt (RFC 9116) — no published security contact",
                           fix="Add /.well-known/security.txt with Contact: and Policy: fields."))
    else:
        out.append(finding("DIS-009", "pass", "security.txt present"))
    return assemble(url, args.context, out, started)


# ---------------------------------------------------------------------------
# Subcommand: links
# ---------------------------------------------------------------------------
def cmd_links(args):
    started = time.time()
    start = args.url
    req_h = request_headers(args)
    out = []
    origin = urlsplit(start)

    robots = None
    robots_res = fetch(f"{origin.scheme}://{origin.netloc}/robots.txt", req_h, args.timeout)
    if not robots_res.error and robots_res.status == 200 and robots_res.raw.strip():
        robots, _ = decode_body(robots_res)
        robots = parse_robots(robots or "")

    def allowed(u):
        if robots is None:
            return True
        p = urlsplit(u)
        return robots_group_allowed(robots, p.path or "/")

    queue = [start]
    seen = {start}
    checked = 0
    broken, chains, skipped = [], [], []
    while queue and checked < args.max_pages:
        cur = queue.pop(0)
        if not allowed(cur):
            skipped.append(cur)
            continue
        res = fetch(cur, req_h, args.timeout)
        if res.error:
            broken.append(f"{cur} -> {res.error}")
            continue
        if res.status >= 400:
            broken.append(f"{cur} -> HTTP {res.status}")
            continue
        checked += 1
        hops = len(res.chain) - 1
        if hops > 2:
            chains.append(f"{cur} ({hops} hops)")
        text, note = decode_body(res)
        if note or not text:
            continue
        page = parse_page(text)
        for href in page.a_hrefs:
            href = href.strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
                continue
            absolute = urljoin(cur, href.split("#", 1)[0])
            p = urlsplit(absolute)
            if p.scheme not in ("http", "https") or (p.netloc, p.scheme) != (origin.netloc, origin.scheme):
                continue
            if absolute not in seen:
                seen.add(absolute)
                queue.append(absolute)
        time.sleep(args.delay)

    if checked == 0 and not broken:
        out.append(finding("LNK-003", "warn", "Start page could not be fetched; crawl produced nothing",
                           evidence=start))
    if broken:
        out.append(finding("LNK-001", "fail", f"{len(broken)} broken internal link(s)",
                           evidence="; ".join(broken[:20]),
                           fix="Fix or remove the dead links."))
    if chains:
        out.append(finding("LNK-002", "info", f"{len(chains)} link(s) pass through long redirect chains",
                           evidence="; ".join(chains[:10])))
    if skipped:
        out.append(finding("LNK-004", "info", f"{len(skipped)} URL(s) skipped by robots.txt",
                           evidence="; ".join(skipped[:5])))
    out.append(finding("LNK-SUM", "info", f"Crawled {checked} page(s), {len(seen)} discovered, "
                                         f"cap {args.max_pages}"))
    return assemble(start, args.context, out, started)


# ---------------------------------------------------------------------------
# Subcommand: secrets
# ---------------------------------------------------------------------------
def cmd_secrets(args):
    started = time.time()
    root = Path(args.dir)
    out = []
    if not root.is_dir():
        out.append(finding("SEC-M-000", "fail", "Directory does not exist", evidence=str(root)))
        return assemble(str(root), args.context, out, started)

    scanned = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(root))
        if path.name.endswith(".map"):
            out.append(finding("SEC-M-001", "fail", "Source map shipped in build output",
                               evidence=rel,
                               fix="Disable source maps (or keep them server-side only) in production builds."))
        if path.name == ".env" or path.name.startswith(".env."):
            out.append(finding("SEC-M-002", "fail", "Dot-env file shipped in build output",
                               evidence=rel, fix="Remove .env from build artifacts; inject env at runtime."))
        try:
            if path.stat().st_size > TH["max_file_bytes"]:
                continue
            text = path.read_text("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        for i, line in enumerate(text.splitlines(), 1):
            for fid, label, rx in SECRET_PATTERNS:
                m = rx.search(line)
                if m:
                    out.append(finding(fid, "fail", f"{label} in build output",
                                       evidence=f"{rel}:{i}: {m.group(0)[:6]}…[redacted]",
                                       fix="Remove the credential, rotate it, and rebuild."))
            if path.suffix.lower() in DANGEROUS_API_EXTS:
                for fid, label, rx in DANGEROUS_API_PATTERNS:
                    if rx.search(line):
                        out.append(finding(fid, "warn", f"{label} sink in shipped code",
                                           evidence=f"{rel}:{i}",
                                           fix="Review the sink: escape or framework-fence any user-controlled input before it reaches it."))
                        break  # one sink per line is enough signal
                if WILDCARD_POSTMESSAGE_RE.search(line):
                    out.append(finding("SEC-M-007", "warn", "postMessage with '*' target origin",
                                       evidence=f"{rel}:{i}",
                                       fix="Pin the exact target origin — '*' lets any window receive messages."))
            if path.suffix.lower() in GENERIC_SECRET_EXTS:
                m = GENERIC_SECRET_RE.search(line)
                if m:
                    out.append(finding("SEC-M-005", "warn", "Hard-coded credential-looking assignment",
                                       evidence=f"{rel}:{i}: {m.group(0)[:6]}…[redacted]",
                                       fix="Verify and move real secrets out of the bundle."))
                    break  # one hit per file is enough signal
    out.append(finding("SEC-SUM", "info", f"Scanned {scanned} text file(s) under {root}"))
    return assemble(str(root), args.context, out, started)


# ---------------------------------------------------------------------------
# Subcommand: privacy
# ---------------------------------------------------------------------------
def _find_policy_link(page, base_url, tokens, substrings):
    """First <a href> whose path matches the vocabulary; None when absent."""
    for href in page.a_hrefs:
        h = (href or "").strip()
        if not h or h.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        low = h.lower()
        parts = re.split(r"[^a-z0-9]+", low)
        if any(t in parts for t in tokens) or any(s in low for s in substrings):
            return urljoin(base_url, h.split("#", 1)[0])
    return None


def _probe_paths(base_url, paths, req_h, timeout, allowed=None, skipped=None):
    """First common path that answers < 400; None when all fail. Paths the
    robots predicate rejects are skipped and recorded for the summary."""
    for path in paths:
        if allowed is not None and not allowed(path):
            if skipped is not None:
                skipped.append(path)
            continue
        res = fetch(urljoin(base_url, path), req_h, timeout)
        if not res.error and res.status < 400:
            return res
    return None


def cmd_privacy(args):
    started = time.time()
    url = args.url
    req_h = request_headers(args)
    out = []
    res = fetch(url, req_h, args.timeout)
    if res.error:
        out.append(finding("NET-001", "fail", "Target unreachable",
                           evidence=f"{url} -> {res.error}"))
        return assemble(url, args.context, out, started)

    text, note = decode_body(res)
    if note or not text:
        out.append(finding("BODY-001", "review",
                           f"Body not decoded ({note}); privacy checks need a browser"))
        return assemble(url, args.context, out, started)

    page = parse_page(text)
    base = res.url or url

    # Third-party trackers in the static HTML.
    found_hosts = set()
    for src in page.script_srcs:
        host = (urlsplit(src).hostname or "").lower()
        if not host:
            continue
        for entry in KNOWN_TRACKER_HOSTS:
            if host == entry or host.endswith("." + entry):
                found_hosts.add(entry)
    if found_hosts:
        out.append(finding("PRV-010", "review",
                           f"{len(found_hosts)} known third-party tracker host(s) in static HTML; "
                           "verify in a browser that they only fire after consent",
                           evidence=", ".join(sorted(found_hosts)),
                           fix="Gate these scripts behind the consent banner, or drop them."))
    elif page.is_spa_shell():
        out.append(finding("PRV-011", "review",
                           "SPA shell: static HTML cannot rule out JS-injected trackers; "
                           "verify rendered DOM in the browser layer"))
    else:
        out.append(finding("PRV-011", "pass", "No known third-party trackers in static HTML"))

    # Robots.txt gates the probe paths (the UA string promises we respect it).
    origin = urlsplit(base)
    robots = None
    robots_res = fetch(f"{origin.scheme}://{origin.netloc}/robots.txt", req_h, args.timeout)
    if not robots_res.error and robots_res.status == 200 and robots_res.raw.strip():
        robots_text, _ = decode_body(robots_res)
        robots = parse_robots(robots_text or "")
    skipped_probes = []

    def probe_allowed(path):
        return robots is None or robots_group_allowed(robots, path)

    # Privacy policy: discover via link scan, fall back to common-path probes.
    policy_link = _find_policy_link(page, base, PRIVACY_LINK_TOKENS, PRIVACY_LINK_SUBSTRINGS)
    policy_res = (fetch(policy_link, req_h, args.timeout) if policy_link
                  else _probe_paths(base, PRIVACY_PATH_PROBES, req_h, args.timeout,
                                    allowed=probe_allowed, skipped=skipped_probes))
    if policy_link is None and policy_res is None:
        out.append(finding("PRV-001", "warn", "No privacy policy link found on the page",
                           evidence=f"link-keyword scan + {len(PRIVACY_PATH_PROBES)} common-path probes empty",
                           fix="Link the privacy policy from every page (footer) at a stable URL."))
    else:
        out.append(finding("PRV-001", "pass", "Privacy policy found",
                           evidence=policy_link or policy_res.url))
        if policy_res.error or policy_res.status >= 400:
            out.append(finding("PRV-003", "warn", "Privacy policy page unreachable",
                               evidence=f"GET {policy_link or policy_res.url} -> "
                                        f"{policy_res.error or policy_res.status}"))
        else:
            out.append(finding("PRV-003", "pass", "Privacy policy page reachable",
                               evidence=policy_res.url))
            doc_text, doc_note = decode_body(policy_res)
            if doc_note or not doc_text or not any(
                    k in doc_text.lower() for k in PRIVACY_PAGE_KEYWORDS):
                out.append(finding("PRV-005", "review",
                                   "Privacy policy lacks the keyword floor; read it and judge "
                                   "content adequacy (CMP-003)",
                                   evidence=f"GET {policy_res.url}"))
            else:
                out.append(finding("PRV-005", "pass", "Privacy policy contains the keyword floor"))

    # Terms: same discovery, no keyword floor.
    terms_link = _find_policy_link(page, base, TERMS_LINK_TOKENS, TERMS_LINK_SUBSTRINGS)
    terms_res = (fetch(terms_link, req_h, args.timeout) if terms_link
                 else _probe_paths(base, TERMS_PATH_PROBES, req_h, args.timeout,
                                   allowed=probe_allowed, skipped=skipped_probes))
    if terms_link is None and terms_res is None:
        out.append(finding("PRV-002", "warn", "No terms link found on the page",
                           evidence=f"link-keyword scan + {len(TERMS_PATH_PROBES)} common-path probes empty",
                           fix="Link the terms of service from every page (footer) at a stable URL."))
    else:
        out.append(finding("PRV-002", "pass", "Terms found",
                           evidence=terms_link or terms_res.url))
        if terms_res.error or terms_res.status >= 400:
            out.append(finding("PRV-004", "warn", "Terms page unreachable",
                               evidence=f"GET {terms_link or terms_res.url} -> "
                                        f"{terms_res.error or terms_res.status}"))
        else:
            out.append(finding("PRV-004", "pass", "Terms page reachable",
                               evidence=terms_res.url))

    out.append(finding("PRV-SUM", "info",
                       f"Privacy scan: trackers={len(found_hosts)} host(s); "
                       f"policy={'found' if (policy_link or policy_res) else 'missing'}; "
                       f"terms={'found' if (terms_link or terms_res) else 'missing'}; "
                       f"robots-skipped probes={len(skipped_probes)}"))
    return assemble(url, args.context, out, started)


# ---------------------------------------------------------------------------
# Subcommand: security
# ---------------------------------------------------------------------------
def cmd_security(args):
    started = time.time()
    url = args.url
    req_h = request_headers(args)
    out = []
    res = fetch(url, req_h, args.timeout)
    if res.error:
        err = res.error
        if any(sig in err for sig in TLS_ERROR_SIGNATURES):
            out.append(finding("SEC-X-050", "fail", "TLS certificate verification failed",
                               evidence=f"{url} -> {err}",
                               fix="Fix the certificate (expired, self-signed, or hostname mismatch) — this is a cert problem, not infrastructure."))
        out.append(finding("NET-001", "fail", "Target unreachable",
                           evidence=f"{url} -> {err}"))
        return assemble(url, args.context, out, started)

    text, note = decode_body(res)
    if note or not text:
        out.append(finding("BODY-001", "review",
                           f"Body not decoded ({note}); security checks need a browser"))
        return assemble(url, args.context, out, started)

    page = parse_page(text)
    base = res.url or url
    origin_host = (urlsplit(base).hostname or "").lower()
    hdr = res.headers

    # Reference response for "what does this server do with unknown paths" —
    # lets us tell framework rewrites (SPA fallback) apart from real exposure.
    fallback = fetch(urljoin(base, "/definitely-not-here-audit-probe"), req_h, args.timeout)
    fb_text, fb_note = (None, "no-fallback")
    if not fallback.error and fallback.status >= 400:
        fb_text, fb_note = decode_body(fallback)
    fb_digest = (hashlib.sha256(fb_text.encode("utf-8", "replace")).hexdigest()
                 if fb_text and not fb_note else None)

    # 1) Sensitive path exposure (GET-only probes).
    exposed, protected = [], []
    for path, label in SECURITY_PROBE_PATHS:
        r = fetch(urljoin(base, path), req_h, args.timeout)
        if r.error:
            continue
        if r.status in (401, 403):
            protected.append(f"{path} ({r.status})")
            continue
        if r.status == 200 and r.raw:
            t, n = decode_body(r)
            digest = (hashlib.sha256((t or "").encode("utf-8", "replace")).hexdigest()
                      if not n else None)
            if fb_digest is not None and digest == fb_digest:
                continue  # SPA/framework rewrite of unknown paths, not exposure
            exposed.append(f"{path} -> HTTP 200 ({label})")
    if exposed:
        out.append(finding("SEC-X-001", ctx_status(args, "fail"),
                           f"{len(exposed)} sensitive path(s) exposed on the server",
                           evidence="; ".join(exposed[:6]),
                           fix="Remove these files/endpoints from the deployment; serve 404/403."))
    else:
        extra = f"; {len(protected)} protected (401/403)" if protected else ""
        out.append(finding("SEC-X-001", "pass",
                           f"No sensitive paths exposed ({len(SECURITY_PROBE_PATHS)} probed{extra})"))

    # 2) SRI on cross-origin scripts/stylesheets.
    sri_missing = []
    for tag, src, has_integrity in page.ext_resources:
        host = (urlsplit(src).hostname or "").lower()
        if not host or host == origin_host or has_integrity:
            continue
        if any(host == e or host.endswith("." + e) for e in KNOWN_TRACKER_HOSTS):
            sri_missing.append(f"{tag} {src} (dynamic loader; SRI n/a — restrict via CSP)")
        else:
            sri_missing.append(f"{tag} {src}")
    hard = [e for e in sri_missing if "dynamic loader" not in e]
    if hard:
        out.append(finding("SEC-X-010", "warn",
                           f"{len(hard)} cross-origin resource(s) without SRI",
                           evidence="; ".join(sri_missing[:6]),
                           fix='Add integrity="sha384-…" to CDN scripts/stylesheets, or self-host.'))
    elif sri_missing:
        out.append(finding("SEC-X-010", "info",
                           "Cross-origin scripts without SRI are all dynamic loaders (tag managers)",
                           evidence="; ".join(sri_missing[:4])))
    else:
        out.append(finding("SEC-X-010", "pass", "No cross-origin resources, or all carry integrity"))

    # 3) CSP quality (presence itself is the headers subcommand's SEC-001).
    csp = (hdr.get("Content-Security-Policy") if hdr else "") or ""
    csp_ro = (hdr.get("Content-Security-Policy-Report-Only") if hdr else "") or ""
    if csp:
        directives = {}
        for part in csp.split(";"):
            bits = part.strip().split()
            if bits:
                directives[bits[0].lower()] = bits[1:]
        script_dirs = directives.get("script-src", directives.get("default-src", []))
        problems = []
        if "unsafe-inline" in script_dirs:
            problems.append("'unsafe-inline' in script context")
        if "unsafe-eval" in script_dirs:
            problems.append("'unsafe-eval' in script context")
        if "*" in script_dirs:
            problems.append("wildcard script source list")
        if not script_dirs:
            problems.append("no script-src/default-src allowlist")
        style_inline = "unsafe-inline" in directives.get(
            "style-src", directives.get("default-src", []))
        style_note = " (style-src 'unsafe-inline' is common; tighten when practical)" if style_inline else ""
        if problems:
            out.append(finding("SEC-X-020", "warn", "CSP present but weak: " + "; ".join(problems),
                               evidence=csp[:200],
                               fix="Allow-list script sources; nonce/hash-based CSP instead of unsafe keywords."))
        else:
            out.append(finding("SEC-X-020", "pass", "CSP restricts script sources" + style_note))
    elif csp_ro:
        out.append(finding("SEC-X-020", "info", "CSP is Report-Only — enforce it before launch",
                           evidence=csp_ro[:120]))
    else:
        out.append(finding("SEC-X-020", "info",
                           "No CSP header to grade here (presence itself is SEC-001 in the headers subcommand)"))

    # 4) 404 page debug leak (reuses the fallback reference response).
    if fb_text:
        hits = [s for s in DEBUG_LEAK_SIGNATURES if s in fb_text]
        if hits:
            out.append(finding("SEC-X-030", "warn", "Not-found page leaks framework/debug details",
                               evidence="; ".join(hits[:3]),
                               fix="Return a generic styled 404 and disable debug mode in production."))
        else:
            out.append(finding("SEC-X-030", "pass", "404 page carries no framework/debug signatures"))

    # 5) CORS: wildcard = info; arbitrary-Origin reflection + credentials = fail.
    acao = (hdr.get("Access-Control-Allow-Origin") if hdr else "") or ""
    acac = (hdr.get("Access-Control-Allow-Credentials") if hdr else "") or ""
    if acao:
        probe_origin = "https://release-audit-probe.example"
        refl = fetch(url, {**req_h, "Origin": probe_origin}, args.timeout)
        racao = (refl.headers.get("Access-Control-Allow-Origin") if refl.headers else "") or ""
        if "true" in acac.lower() and racao == probe_origin:
            out.append(finding("SEC-X-040", ctx_status(args, "fail"),
                               "CORS reflects arbitrary Origin with credentials allowed",
                               evidence=f"probe Origin echoed as ACAO: {racao}; Allow-Credentials: {acac}",
                               fix="Allow-list known origins; never reflect arbitrary origins with credentials."))
        elif acao.strip() == "*":
            out.append(finding("SEC-X-040", "info",
                               "CORS allows any origin — fine for public data; verify private endpoints do not share this config",
                               evidence="Access-Control-Allow-Origin: *"))
        else:
            out.append(finding("SEC-X-040", "pass", f"CORS restricted: {acao[:60]}"))
    else:
        out.append(finding("SEC-X-040", "info", "No CORS headers on this page (same-origin only)"))

    out.append(finding("SEC-X-SUM", "info",
                       f"Security scan: {len(exposed)} exposed path(s), {len(sri_missing)} SRI gap(s), "
                       f"csp={'graded' if (csp or csp_ro) else 'absent'}"))
    return assemble(url, args.context, out, started)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(prog="release_audit",
                                 description="Deterministic pre-release checks (web-app-release-skill).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("headers", help="TLS, redirects, security headers, cookies, compression, mixed content")
    p.add_argument("url")
    add_common_args(p)
    p.set_defaults(func=cmd_headers)

    p = sub.add_parser("security", help="sensitive-path exposure, SRI, CSP quality, CORS, 404 debug leak, TLS diagnosis")
    p.add_argument("url")
    add_common_args(p)
    p.set_defaults(func=cmd_security)

    p = sub.add_parser("meta", help="title/description/canonical/OG/H1/JSON-LD/favicon checks")
    p.add_argument("url")
    add_common_args(p)
    p.set_defaults(func=cmd_meta)

    p = sub.add_parser("discovery", help="robots.txt, sitemap.xml validity + cross-checks, llms.txt")
    p.add_argument("url")
    add_common_args(p)
    p.set_defaults(func=cmd_discovery)

    p = sub.add_parser("links", help="same-origin crawl for broken links and redirect chains")
    p.add_argument("url")
    p.add_argument("--max-pages", type=int, default=TH["links_max_pages"])
    p.add_argument("--delay", type=float, default=TH["links_delay"])
    add_common_args(p)
    p.set_defaults(func=cmd_links)

    p = sub.add_parser("secrets", help="source maps, .env files, credential patterns in a build dir")
    p.add_argument("dir")
    add_common_args(p)
    p.set_defaults(func=cmd_secrets)

    p = sub.add_parser("privacy", help="privacy/terms link discovery, page reachability, third-party trackers in static HTML")
    p.add_argument("url")
    add_common_args(p)
    p.set_defaults(func=cmd_privacy)

    args = ap.parse_args(argv)
    report = args.func(args)
    output_and_exit(report, args, args.cmd)


if __name__ == "__main__":
    main()
