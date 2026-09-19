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

## Known limitations (v1.1)

- Single site per audit (no monorepo multi-app).
- Auth flows only via cookie passthrough; login automation is delegated.
- GEO citability and compliance are judgment checks, not certifications.
- Walkthrough baseline was contaminated by auto-trigger; a clean baseline
  requires a session without the skill installed.
