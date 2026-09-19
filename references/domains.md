# Domains, checks and thresholds

What to check per release domain. Rows with a script ID are decided by
`scripts/release_audit.py` — run it, don't re-derive. Rows marked *judgment*
are yours to verify; the "how" column says what counts as evidence.

Threshold sources were last reviewed **2026-09**; re-check before relying on
numbers that may have moved (Core Web Vitals, crawler lists).

## 1. Build hygiene (BUILD)

| Check | Standard / how | Fix |
|---|---|---|
| SEC-M-001..005 | Script `secrets <dist>`: no source maps, no .env, no credential patterns in the bundle | Rotate any leaked credential, rebuild |
| Build passes (judgment) | Run the project's build command; a release audit on a red build stops there | Fix build errors first |
| Dependency vulns (judgment) | `npm audit --omit=dev` / `pnpm audit --prod`; block on high/critical in prod deps | Bump or patch; document accepted risk |
| Types/lint/tests (judgment) | Project's own checks green | Fix before further audit |

## 2. HTTP & infrastructure (headers script)

| ID | Check | Standard |
|---|---|---|
| HTTP-001/002 | HTTPS everywhere, HTTP→HTTPS 301 | All major checklists; skip on `preview` context (warn) |
| SEC-001 | Content-Security-Policy present | Start `Content-Security-Policy-Report-Only`, tighten, then enforce |
| SEC-002/003/004/005 | XCTO nosniff · X-Frame-Options or CSP frame-ancestors · Referrer-Policy · Permissions-Policy | OWASP Secure Headers project |
| SEC-006 | HSTS once HTTPS enforced (production) | e.g. `max-age=31536000` |
| SEC-007 | Cookies: Secure · HttpOnly · SameSite | Session + auth cookies at minimum |
| COMP-001 / PERF-002 | gzip/brotli/zstd on HTML | Lighthouse "text compression" audit |
| PERF-003 | Cache-Control on documents | HTML `no-cache`; hashed assets `immutable` |
| MIXED-001 | No http:// subresources on HTTPS pages | Browser blocks/mixed-badge risk |
| REDIR-001 | Redirect chains ≤ 3 hops | Each hop adds latency; update links |

## 3. SEO (meta / discovery / links scripts)

| ID | Check | Standard |
|---|---|---|
| SEO-001/002 | Title present, 10–60 chars | Front-End Checklist (2026): unique per page, ~50–60 chars |
| SEO-003/004 | Meta description present, 50–160 chars | Same source |
| SEO-005 | `rel=canonical` → final URL (no redirect targets) | Front-End Checklist |
| SEO-006/007 | Exactly one descriptive `<h1>` | Same source |
| SEO-008/009 | JSON-LD valid; present on content pages | schema.org; validate in browser for SPAs |
| SEO-010 | No accidental `noindex` on key routes | Homepage noindex = P0 |
| SOC-001..003 | OG title/description; og:image ~1200×630 | Front-End Checklist: 1200×630 recommended |
| DIS-000..008 | robots.txt reachable; sitemap valid; no 4xx/noindex/robots-blocked URLs inside the sitemap | sitemaps.org protocol |
| LNK-001..004 | No broken internal links; chains ≤ 2 hops | Crawl evidence from `links` |
| PWA-001/002 | Favicon set; manifest linked | Front-End Checklist |
| BASE-001/002 · A11Y-001 | charset · viewport · `lang` | HTML spec / WCAG 3.1.1 |
| SPA shells (JS-001) | Never fail static-HTML checks on a client-rendered shell — verify rendered DOM in a browser first | SEO audit lesson: JS-injected tags are invisible to static fetches |

## 4. GEO — AI search readiness (partly script, partly judgment)

Script: `GEO-001/002` (llms.txt), `DIS-007` (AI crawler rules summary).

AI crawler policy (judgment): decide **deliberately**, per business goal, which
of these may crawl. There is no universally correct answer; an unstated default
is the finding. List reviewed 2026-09:

`GPTBot, OAI-SearchBot, ChatGPT-User, ClaudeBot, Claude-User, Claude-SearchBot,
PerplexityBot, Perplexity-User, Google-Extended, Applebot-Extended, Bytespider,
CCBot, Amazonbot, Meta-ExternalAgent`

Citability checklist (judgment; verify on rendered pages):
- Server-rendered or prerendered HTML — AI fetchers do not run your JS.
- Question-shaped H2s with a direct 40–60 word answer directly under them.
- Facts/numbers in tables or short lists, with sources and a visible date.
- Author + last-updated on content pages; `FAQPage`/`HowTo` schema where honest.
- Stable, descriptive slugs; no content gated behind interaction.
- `llms.txt`: a short markdown map of key pages at `/llms.txt` (emerging
  standard — recommend, don't demand).

Sources: Google "Optimizing for generative AI" guide (developers.google.com,
2026); llms.txt proposal (llmstxt.org).

## 5. Performance (run_lighthouse.sh + judgment)

| Check | Threshold | Source |
|---|---|---|
| Lighthouse Performance | ≥ 90 (mobile, lab) | web.dev/Lighthouse, reviewed 2026-09 |
| LCP / CLS / INP | < 2.5 s / < 0.1 / < 200 ms (75th percentile field data) | web.dev Core Web Vitals |
| Page weight | < 1500 KB total; JS < 300 KB compressed | Front-End Checklist; addyosmani/web-quality-skills budgets |
| Fonts/images | woff2 + preload; WebP/AVIF with fallback | same |

Lab scores from `run_lighthouse.sh` are evidence, not verdicts — pair a failing
score with the trace file it emits before prescribing fixes.

## 6. Accessibility (delegation + judgment)

- Static code review: delegate to `web-design-guidelines` (cheap, high signal).
- Runtime: Lighthouse accessibility category; `npx axe` per key page if available.
- Spot-check in browser: keyboard-only path through the main flow, visible focus,
  contrast ≥ 4.5:1 body text, 400% zoom reflow without horizontal scroll.
- Lighthouse a11y 100 ≠ WCAG conformant — report automated score as coverage,
  never as certification.

## 7. Functional QA (delegation)

- Minimum: smoke the P0 flows (signup, login, core action, purchase if any) via
  `browser-use:web-gui-tester` with a written test plan.
- Console must be clean of errors on key routes (capture evidence per route).
- 404 page exists and is styled (check any LNK-001 target by hand).
- Full exploratory pass = `dogfood` — only on explicit request (expensive).

## 8. Privacy & compliance — GDPR / terms / privacy policy (script `privacy` + judgment; never legal advice)

Three steps: **triage** whether GDPR applies → deterministic evidence (script
`PRV-*`) plus browser evidence → judgment checklist (`CMP-*`) and the processor
questionnaire. Everything is presence/config with evidence; every finding says
"confirm obligations with counsel". Never state or imply legal compliance.

### Step 0 — GDPR applicability triage (always run; cheap)

Record one of: "GDPR applies" or "does not apply — because …". Signals:
EU locales/hreflang, EUR pricing, `.eu` domain, EU-targeted marketing,
analytics collecting EU visitors. Non-applicability: explicit EU/EEA
geo-blocking or an internal-only tool. **An unstated default is the finding**
(CMP-002). Adjacent regimes (UK GDPR, CCPA/CPRA): one awareness line, not a
full pass.

### Script layer — `release_audit.py privacy <url>` (homepage + one key route)

| ID | Check | Standard / how |
|---|---|---|
| PRV-001/002 | Privacy policy / terms link discoverable | `<a href>` slug keywords + common-path probes (/privacy, /privacy-policy, /datenschutz, /terms, /agb, …) |
| PRV-003/004 | Discovered policy / terms page fetches 200 | 404/error → warn |
| PRV-005 | Policy page contains a keyword floor (personal data, cookie(s), GDPR/DSGVO, privacy, 隐私 …) | floor only — content adequacy is CMP-003 |
| PRV-010 | Known third-party trackers in static HTML (`KNOWN_TRACKER_HOSTS` in the script, compiled 2026-09) | `review` — resolve in the browser layer before assigning severity |
| PRV-011 | No known trackers in static HTML (JS-injected tags are invisible; SPA caveat) | pass |

### Browser layer (evidence for CMP-005/006/007)

- For each PRV-010 `review`: watch network activity before any consent
  interaction — a tracker request that fires pre-consent → CMP-005.
- Banner quality: reject as easy to reach as accept? granular categories?
  choice changeable later? (CMP-006)
- Account-holding apps: a delete-account / data-export entry point exists —
  presence only, never submit real data. (CMP-007)

### Judgment checklist (CMP-*; default severities — `severity_overrides` wins)

| ID | Check | Default |
|---|---|---|
| CMP-001 | Collecting personal data with no privacy policy | P0 |
| CMP-002 | GDPR applicability never assessed / decision unrecorded | P2 |
| CMP-003 | Policy missing required disclosures: controller identity & contact, purposes, legal bases, data categories, recipients, third-country transfers + basis, retention periods, data-subject rights, right to lodge a complaint | P1 |
| CMP-004 | No terms of service on an account-holding or purchase app | P2 |
| CMP-005 | Third-party trackers fire before consent (EU-facing) | P1 |
| CMP-006 | Consent banner one-sided (reject harder than accept, no granularity, no withdrawal) | P2 |
| CMP-007 | No data-subject-rights affordances (account deletion / data export) | P1 (saas-app, e-commerce) |
| CMP-008 | Processor questionnaire incomplete: vendors without DPA; transfers without SCC/adequacy basis | P2 |
| CMP-009 | High-risk processing without a DPIA (large-scale profiling, special-category data, children's data) | P2 |
| CMP-010 | Retention schedule / breach-response process unknown | P3 |

CMP-001..010 are fixed IDs; new ones continue from CMP-011.

### Processor & governance questionnaire (ask; record answers as findings — the user's statement is the evidence)

Vendors (hosting, analytics, email, error tracking, payments) × DPA in place? ·
EU→third-country transfers and their basis (SCCs, adequacy) · retention periods
per data store · breach-notification owner + 72-hour path · DPIA status.

| Also in this domain | How |
|---|---|
| Analytics present | Tag/snippet in rendered HTML or confirmed event in the tool |
| Accessibility statement | Recommend for EU-facing products (EAA) |

### Remediation: reference-policy research (only on user request; never legal advice)

When CMP-001/003/004 fires, drafting belongs to a one-time project with
counsel — the gate verifies presence/config only. On explicit request, help
the fix with a **disclosure-coverage diff, never text reuse**: fetch 1–2
reference policies the user names (a large vendor in the same space works
well) and diff them against the CMP-003 disclosure list — which required
items they carry that ours lacks. Two hard lines: (1) never copy wording —
policy text is copyrighted, and a borrowed policy describes *their* vendors,
retention and transfers; a policy that misstates this app's practices is
itself a transparency violation (Arts. 12–14). The §8 questionnaire output is
what the real policy must match. (2) no legal-risk judgement — record open
questions as findings for the user to raise with counsel.

Sources: GDPR (EUR-Lex 32016R0679) Arts. 3, 6–8, 12–14, 15–22, 25, 28, 30,
32–35 · EDPB guidelines (edpb.europa.eu) · ICO GDPR checklist (ico.org.uk) ·
CNIL cookies guidance — reviewed 2026-09. Presence/config checks only — confirm
obligations with counsel.

## 9. Release ops (questionnaire + artifacts; never assume)

Ask the user / check for: environment parity (env vars present in the target),
backward-compatible DB migration + backup taken, documented rollback (one
command or link), health endpoint returning 200, monitoring/alerting receiving a
test event, feature flags defaulting safe. Record answers as findings with the
user's statement as evidence — do not fabricate infrastructure claims.
