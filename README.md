# web-app-release-skill

A gate-style **release audit skill** for AI coding agents (ZCode / Claude Code /
any agent that reads `SKILL.md`). Point it at a web app and it runs a
pre-launch audit across nine domains, then produces an evidence-backed
scorecard with an explicit **GO / NO-GO** verdict — and re-verifies after you
deploy.

```
User: "帮我给 https://preview.example.com 做上线前体检，给我 go/no-go 结论"
Agent: [runs the gate] → release-audit/2026-09-20-preview.example.com.md → NO-GO (4×P0) →
       remediation loop → GO
```

## Why

Existing agent skills cover fragments (SEO audits, Lighthouse, UI guidelines,
exploratory QA) but none of them provide:

1. a **deterministic script layer** (repeatable pass/fail, CI-friendly exit codes),
2. a **gate loop**: P0–P3 findings → remediation → re-check → verdict → post-deploy verify,
3. **delegation** to the specialist skills you already have,
4. hosting-agnostic defaults (no Cloudflare/Vercel lock-in).

This skill is the orchestrator: scripts for facts, methodology for judgment,
other skills for deep QA, one scorecard for the decision.

## Install

```bash
npx skills add https://github.com/bigdong89/web-app-release-skill
# or: cp -r skills/* into your agent skills directory / symlink the folder
```

The skill triggers on launch/release/ship/go-live intents (EN + 中文触发词:
发布前检查 / 上线体检 / 发版前核查), or invoke it directly.

## What it checks

| Domain | Deterministic (script) | Judgment (agent) |
|---|---|---|
| Build hygiene | source maps / .env / credential patterns in dist | build, `npm audit`, tests |
| HTTP & infra | TLS, redirect chains, 7 security headers, cookie flags, compression, mixed content | — |
| SEO | title/description/canonical/H1/JSON-LD/OG/favicon, robots.txt, sitemap validity + cross-checks, dead links | — |
| GEO (AI search) | llms.txt, AI-crawler robots rules | citability heuristics |
| Performance | Lighthouse runner (graceful skip) | CWV vs thresholds, budgets |
| Accessibility | — | axe/Lighthouse + `web-design-guidelines` delegation |
| Functional QA | — | delegation to `web-gui-tester` / `dogfood` |
| Privacy & compliance | `privacy` subcommand: policy/terms link discovery, reachability, third-party tracker detection | GDPR applicability triage, CMP-001..010 checklist, consent-order browser evidence, processor questionnaire (no legal advice) |
| Release ops | health endpoint | migrations/rollback/monitoring questionnaire |

Design details and threshold sources: [`references/domains.md`](references/domains.md) ·
prior-art survey: [`docs/research.md`](docs/research.md).

## How a run works

1. **Recon** — detect stack/site type, read optional `.release-check.yml` (target URL, key routes, context, thresholds), ask ≤3 questions.
2. **Audit** — `scripts/release_audit.py` (`headers` / `meta` / `discovery` / `links` / `secrets` / `privacy`) → browser checks for SPA shells and consent order → judgment items → optional delegation.
3. **Verdict** — scorecard + findings with quoted evidence → **GO iff zero P0**.
4. **Remediate** — fix, re-run the owning check, log before/after evidence.
5. **Post-deploy** — re-verify the deployed URL, smoke the critical path, confirm monitoring/rollback.

Scripts are environment-aware: `--context preview` downgrades TLS/header noise,
loopback targets never produce TLS P0s, `github.io`-style hosts get header
warnings instead of false fails, and client-rendered SPA shells yield
`review` status instead of false negatives. `--gate` exits 1 on any fail for CI.

## Testing

Acceptance is fixture-driven: [`tests/`](tests/) serves a deliberately broken
site and asserts every planted defect is detected — currently **89/89**.

```bash
python3 tests/run_fixture_tests.py
```

Evaluation history and iteration log: [`EVALUATIONS.md`](EVALUATIONS.md).

## License

[MIT](LICENSE). Standing on the shoulders of MIT-licensed prior art —
[samber/cc-skills](https://github.com/samber/cc-skills),
[addyosmani/web-quality-skills](https://github.com/addyosmani/web-quality-skills),
[coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) —
and public checklists (Front-End Checklist, web.dev CWV, Google's generative-AI
optimization guide). Attribution details in [docs/research.md](docs/research.md).
