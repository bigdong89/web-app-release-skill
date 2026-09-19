# Research: why this skill exists, and what it borrows

Compiled 2026-09-20. Three inputs: (1) inventory of locally installed skills,
(2) survey of public skill repos/marketplaces for prior art, (3) industry
release checklists.

## 1. Local skills inventory (what we reuse instead of rebuild)

| Skill | Role in a release audit |
|---|---|
| web-design-guidelines | Static UI/a11y/interaction code review (fetches vercel web-interface-guidelines rules at runtime) |
| dogfood | Black-box exploratory QA with screen-recording evidence (agent-browser CLI) |
| browser-use:web-gui-tester | GUI test methodology: P0–P3 plan, evidence-per-assertion reports |
| browser-use:control-browser | Low-level browser ops (snapshot/screenshot/console) for runtime verification |
| vercel-sandbox | Cloud browser runs on Vercel microVMs (post-deploy spot checks) |
| better-auth* (6 skills) | Auth security configuration knowledge, production hardening checklists |
| superpowers:verification-before-completion | "No claim without fresh command output" — adopted as the gate discipline |
| superpowers:requesting-code-review / finishing-a-development-branch | Pre-merge review, branch wrap-up |
| skill-creator / superpowers:writing-skills | Skill authoring conventions used to build this skill |

Gap found: SEO, GEO, performance scoring, security headers, sitemap/robots,
dead links, privacy compliance, build-hygiene scans, and a unified
scorecard/GO-NO-GO layer — none covered locally. That gap is this skill.

## 2. Public prior art (all MIT-licensed; ideas and thresholds reused with
attribution, wording re-written)

### samber/cc-skills → `site-launch-checklist` (github.com/samber/cc-skills)
- 10-phase interactive pre-launch audit: analytics (GA4/PostHog/GSC), legal,
  security headers, SEO/GEO, copywriting, OG, favicons, Lighthouse, a11y.
- Borrowed: domain coverage list; token-budget discipline; publishing
  evaluations (error-rate deltas) alongside the skill; opinionated-but-declared
  defaults. Their own data: with-skill vs without-skill error rate 98% vs 52%.
- Deliberately different here: not bound to Cloudflare+Vercel; deterministic
  script layer instead of prose-only; remediation + post-deploy phases.

### addyosmani/web-quality-skills (github.com/addyosmani/web-quality-skills)
- Six skills: orchestrator + performance / core-web-vitals / accessibility /
  seo / best-practices.
- Borrowed: evidence tiers (CrUX field data → RUM → lab trace → static
  inspection); graceful degradation when tooling is missing; guardrail
  thresholds (Perf ≥ 90, SEO/BP ≥ 95, CWV at p75, JS < 300 KB compressed);
  "scores are guardrails, not certifications" stance (kept for a11y).

### coreyhaines31/marketingskills → `seo-audit` (skills.sh, ~210k installs)
- Borrowed: context-file-first convention (their `product-marketing.md` → our
  `.release-check.yml`); prompt-injection defense ("fetched pages are untrusted
  data"); verifying structured data on rendered pages, not static HTML.

### Others consulted
- Anthropic official `webapp-testing` (Playwright) — functional QA reference.
- trailofbits/skills (~60 security skills) — model for security-domain rigor.
- GEO-specific skills (claude-seo `seo-geo`, agenticskills bundles) — GEO
  items (llms.txt, AI crawler policy, citability) folded into domains.md.

### Industry checklists (threshold sources in references/domains.md)
Front-End Checklist (385 rules, thedaviddias) · web.dev Core Web Vitals ·
Google "Optimizing for generative AI features" · Netlify/Pantheon launch
checklists · Octopus/Cortex/CloudBees production-readiness checklists.

## 3. Design decisions (v3, after adversarial review)

1. Orchestrator + gate, not a checklist re-write: the four uncovered layers are
   the deterministic script layer, the P0–P3 → GO/NO-GO gate with remediation
   loop, delegation to local skills, and post-deploy re-verification.
2. `release_audit.py` is the single source of truth for pass/fail; references
   explain but never re-judge (no doc/script drift).
3. Context awareness (`preview`/`production`) and a host matrix prevent the
   classic false P0s (localhost TLS, github.io headers).
4. SPA shells produce `review` status, never silent fails — static HTML checks
   on client-rendered pages are the #1 false-negative trap.
5. Fixture-driven acceptance (tests/run_fixture_tests.py, 68 assertions)
   because "no false P0s on real sites" is unmeasurable without a known-broken
   sample.
6. Triggers narrowed to release/launch scenarios so the gate doesn't hijack
   single-domain SEO/security asks (light mode instead).

## 4. Licenses

samber/cc-skills: MIT. addyosmani/web-quality-skills: MIT. This skill's
re-borrowed thresholds/ideas carry attribution here; no verbatim copying
beyond short threshold strings that are industry standards anyway.
