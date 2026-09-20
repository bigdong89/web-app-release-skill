# Report guide: severities, findings, scorecard

## Severity defaults

Two steps. **Step 1 — script status is authoritative for status.** Map it to a
default severity:

| Script status | Default severity |
|---|---|
| fail | P1 |
| warn | P2 |
| info | P3 |
| review | pending — resolve in the browser layer first, then assign |
| pass | not a finding (feeds the scorecard only) |

**Step 2 — apply escalations, downgrades, overrides (in that order).**

Escalate to **P0**:
- SEC-M-002 / SEC-M-003 / SEC-M-004 (credentials or keys in build output)
- HTTP-001 fail on a **public** production URL (loopback targets are already
  capped at warn by the script)
- SEO-010 noindex on the homepage · NET-001 / SEC-X-050 target unreachable
  (production)
- SEC-X-001 sensitive paths exposed on a **public** production URL
- core-flow failure from functional QA · collecting personal data with no
  privacy policy (CMP-001)

Downgrades:
- host-limited platforms (see site-types.md host matrix)
- environment-caused items under `preview` context (TLS, headers)
- SEC-M-001 note: source maps are P1, even though sibling SEC-M IDs are P0
- PRV-001/002 warns on site types where domain 8 is `—` or `L (if tracking)`
  in the site-types matrix → courtesy info (P3), not a finding

`severity_overrides` in `.release-check.yml` beats all of the above.

**Judgment finding IDs** (invent freely inside these namespaces — never reuse
script IDs): `LH-*` Lighthouse categories (category below threshold on a key
route = P1, attach the report file as evidence) · `FUNC-*` functional QA ·
`CMP-*` compliance (CMP-001..010 are fixed with default severities in
domains.md §8; new IDs continue from CMP-011) · `OPS-*` release ops ·
`DEPLOY-*` deployment-reality mismatches · `A11Y-*` runtime accessibility ·
`GEO-*` content citability.

Quick examples: missing description on `/pricing` (SEO-003 fail) → P1 ·
og:image 100×50 (SOC-003 warn) → P2 · no Cache-Control (PERF-003 info) → P3 ·
`AKIA…` in app.js (SEC-M-004 fail) → escalation → P0 · trackers fire before
consent (CMP-005) → P1 · no privacy policy while personal data is collected
(CMP-001) → escalation → P0.

## Finding anatomy

Every finding in the report is one list item with all of:

```
[SEO-003][P1] Missing meta description on /pricing
Evidence: GET /pricing -> <head> has no description (release_audit meta)
Impact: search/AI snippets fall back to page copy
Fix: add <meta name="description" content="…"> in the pricing layout
Effort: S
```

Evidence is quoted output, a header line, a screenshot reference, or a path —
never "I checked".

## Scorecard

One row per audited domain; status is the worst finding severity inside it
(P0→FAIL, P1→WARN, else PASS; a domain fully outside scope reads `n/a`).

| Domain | Status | P0 | P1 | P2 | P3 |
|---|---|---|---|---|---|
| Build hygiene | PASS | 0 | 0 | 0 | 1 |
| HTTP & infra | FAIL | 1 | 3 | 0 | 0 |

## Verdict

**GO iff zero P0.** Print the rule next to the verdict, list P1s as launch-day
obligations, and never bury the verdict — it goes directly under the title.

## Report mechanics

- Path: `<repo>/release-audit/<YYYY-MM-DD>-<host>.md`; suggest `.gitignore`.
- Language: the conversation's language.
- Sections: Verdict → Scorecard → Findings by domain → Not covered →
  Remediation log → Post-deploy (when run).
- "Not covered" is mandatory honesty: checks skipped because Chrome was
  missing, no build dir existed, auth was unavailable, a delegation was
  declined. Each with a one-line "how to cover later".
- Skeleton: `templates/release-report.md`.
