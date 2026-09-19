# Release Audit — {target host or app name}

Date: {YYYY-MM-DD} · Context: {production|preview} · Auditor: web-app-release-skill v1

## Verdict: {GO | NO-GO}

Rule: GO iff zero P0 findings. {N} P0 found. P1 obligations: {list or "none"}.

## Scorecard

| Domain | Status | P0 | P1 | P2 | P3 |
|---|---|---|---|---|---|
| Build hygiene | | | | | |
| HTTP & infrastructure | | | | | |
| SEO | | | | | |
| GEO (AI search) | | | | | |
| Performance | | | | | |
| Accessibility | | | | | |
| Functional QA | | | | | |
| Privacy & compliance | | | | | |
| Release ops | | | | | |

## Findings

### {Domain name}
- [{ID}][{sev}] {title}
  - Evidence: {quoted command output / header / screenshot / path}
  - Impact: {one line}
  - Fix: {action}
  - Effort: {S|M:L}

## Not covered

- {check} — {why} — {how to cover later}

## Remediation log

| Finding | Fix applied | Re-check evidence | Result |
|---|---|---|---|

## Post-deploy verification

{production URL, smoke results, monitoring receipt, rollback confirmed — or "not run"}
