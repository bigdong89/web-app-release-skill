# Evaluations — web-app-release-skill

Records of test runs, following the skill-creator loop (draft → test prompts →
review → fix). Format borrowed from samber/cc-skills' evaluation practice:
record baseline vs with-skill behaviour, then what changed.

## Run 1 — fixture acceptance (automated), 2026-09-20

- `tests/run_fixture_tests.py`: **68/68 assertions pass** against a deliberately
  broken fixture site (missing headers/title/description/canonical/OG, long
  title, duplicate H1, broken JSON-LD, undersized og:image, SPA shell,
  sitemap∩404, sitemap∩noindex, robots∩sitemap paradox, missing llms.txt,
  dead link, sourcemap/.env/private-key/AWS-key in dist, redaction check,
  --gate exit code, md format).
- `run_lighthouse.sh` smoke on fixture: runs, scores parse (SEO 80 / A11y 69 —
  the planted problems), graceful-skip paths verified by inspection.

## Run 2 — double walkthrough on the fixture site, 2026-09-20

Same user prompt given to two general-purpose agents working on
`http://127.0.0.1:8911` (fixture):

| | A: pointed at the skill | B: no pointer (intended baseline) |
|---|---|---|
| Skill used | Yes — read SKILL.md + references, followed 5 phases, ran all 5 subcommands + lighthouse, used template + severity table | **Auto-triggered the skill from its description** (contaminates the baseline — but validates trigger design) |
| Verdict | NO-GO, 4×P0 (leaked key/private.pem/.env reachable over HTTP; no TLS) | NO-GO, 4×P0 (same set, independently derived) |
| Coverage | Headers/meta/discovery/links/secrets/lighthouse + template + "Not covered" section | Same scripts, less structured; added one insight the skill missed |
| Cost | ~310k tokens / 27 tool uses | ~186k tokens / 19 tool uses |

Cross-validation: both runs reached the same P0 set independently.

### Feedback from run A (verbatim themes) → fixes applied (v1.1)

1. "Severity table has holes — PERF-002, DIS-001/002 and Lighthouse failures
   had no row; I invented IDs (LH-SEO, FUNC-001)" → report-guide.md rewritten:
   status→severity mapping rule + escalation/downgrade lists + judgment ID
   namespaces (LH-*/FUNC-*/CMP-*/OPS-*/DEPLOY-*/A11Y-*/GEO-*).
2. "PERF-003 is P2 in the guide but `info` from the script" → resolved by the
   mapping rule (info→P3); SKILL.md severity summary synced.
3. "SEC-M-001 source maps: P0 or P1?" → explicit: P1 (siblings SEC-M-002/3/4
   escalate to P0).
4. "Report path hardcoded; user said /tmp" → `report_dir` added to
   `.release-check.yml`; explicit user-requested location wins.
5. "URL serves the source dir, not dist — skill never told me to check" →
   SKILL.md Phase 1 step 2: deployment reality check, `DEPLOY-1` finding
   (credit: baseline agent found this root cause first).
6. "localhost HTTP → P0 is noisy" → `release_audit.py` caps HTTP-001 at warn
   for loopback/private targets with an explicit "deferred to deployed URL"
   note; fixture test updated accordingly.

### Exit condition check

Planned exit: two consecutive test rounds needing no SKILL.md changes.
Run 2 produced changes (above) → **not yet met**. Next: re-run the walkthrough
in fresh sessions; exit when a round passes without edits.

## Run 3 — GDPR / terms / privacy-policy section (automated + dogfood), 2026-09-20

Scope: new `release_audit.py privacy` subcommand (PRV-*) + domains.md §8 rewrite
(GDPR applicability triage → PRV evidence → browser consent-order checks →
CMP-001..010 checklist + processor questionnaire).

- `tests/run_fixture_tests.py`: **83/83 assertions pass** (was 68/68). Planted
  scenarios: shop fixture page linking privacy.html/terms.html with
  googletagmanager + hotjar scripts → PRV-010 review, PRV-001..005 pass;
  bare index page → PRV-001/002 warn, PRV-011 pass, PRV-010 absent.
- One implementation bug caught by the new assertions: PRV-004 pass branch
  (terms page reachable) was missing — fixture failed first, fix confirmed by a
  fresh run (the fixture loop working as intended).
- md-format smoke: privacy table renders; `--gate` semantics unchanged
  (`review` never trips the gate).
- Dogfood (read-only): example.com → PRV-001/002 warn; python.org → policy
  found + reachable + keyword floor, terms warn (not linked from the homepage
  footer — link-scan heuristic; adequacy remains the agent layer's call).
- Doc-sync edits: SKILL.md (script list, browser layer, P0/P1 defaults, light
  mode row), report-guide.md (CMP-001 formalized in the P0 list, CMP namespace
  note + examples), site-types.md (triage-always-runs note), README (83/83,
  domain table), integrations.md (consent-order wording), docs/research.md
  (§3 decision 7, §5 GDPR sources).

## Run 4 — self-review fixes (v1.2 follow-up), 2026-09-20

A comprehensive review of the repo surfaced 3 defects + 2 calibration gaps;
all fixed in one pass:

- PRV-011 reported `pass` on SPA shells where static HTML proves nothing —
  now `review` (matches the meta subcommand's SPA discipline). New spa fixture
  assertions also cover the broken-policy-link warn path.
- `privacy` probes ignored robots.txt while the UA string claims otherwise —
  probes now gate on robots; the skipped count lands in PRV-SUM.
- SKILL.md description had no GDPR/privacy trigger words and a stale check
  list — trigger surface extended, list synced; config example gained
  `compliance.gdpr`; report template gained a `GDPR applicability` line under
  the verdict.
- Calibration: PRV-001/002 warns on site types where §8 is `—`/`L` are
  courtesy info (report-guide downgrades), not P2 findings.
- Cleanups: `run_lighthouse.sh` dead FAILED variable removed, JSON parse
  guarded; finding template `{S|M:L}` → `{S|M|L}`.

`tests/run_fixture_tests.py`: **89/89 assertions pass** (was 83/83).
Deferred to a later version: PRV-020 form/signup heuristic (CMP-001 evidence
hook), user-extensible tracker host list, probe-success fixture coverage.

## Known limitations (v1.2)

- Single site per audit (no monorepo multi-app).
- Auth flows only via cookie passthrough; login automation is delegated.
- GEO citability and compliance are judgment checks, not certifications.
- PRV-* is a static-HTML floor: JS-injected trackers and self-hosted
  analytics are invisible to it; consent-order evidence always comes from
  the browser layer, and PRV link discovery is a homepage-footer heuristic.
- Walkthrough baseline was contaminated by auto-trigger; a clean baseline
  requires a session without the skill installed.
