# Delegation protocol

This skill orchestrates; it does not duplicate specialists. Delegate when the
situation matches — but respect cost: never auto-run an expensive skill the
user didn't ask for.

| Situation | Delegate to | Cost | How |
|---|---|---|---|
| Static UI/a11y/interaction review of components | `web-design-guidelines` | Cheap | Invoke with the key component files/patterns; merge its file:line output into your findings |
| Runtime browser checks: rendered OG card, consent banner + tracker-vs-consent firing order (PRV-010), focus visibility, SPA rendered DOM | `browser-use:control-browser` | Cheap | Drive the session browser per that skill's protocol; screenshots are evidence |
| Targeted functional test of P0 flows | `browser-use:web-gui-tester` | Medium | Hand it the flow list + URL + test credentials; require its evidence-per-assertion report |
| Full exploratory QA pass | `dogfood` | Expensive (long session) | Only on explicit user request; point at the target URL and auth state; its issue taxonomy maps to our severities |
| `better-auth` in package.json | `better-auth-best-practices` | Medium | Audit config against its Security section; findings like any other |
| Access-control probing (IDOR / session / auth flows) | `browser-use:web-gui-tester` | Expensive (on request) | Hand over user-approved test credentials + the flows to try; the gate itself never attempts bypass |
| Any completion claim | `superpowers:verification-before-completion` | Free (discipline) | Always: fresh command output before "fixed"/"passing" |
| Release includes code changes heading for merge | `superpowers:requesting-code-review` | Medium | After P0/P1 remediation, before merge |

Rules:

1. One delegation at a time; feed it our findings as its focus areas.
2. A delegated skill's report is input, not a separate deliverable — fold its
   evidence into the single release report.
3. If the delegated skill is unavailable, do the cheap version yourself
   (browser spot-check) and note the gap under "Not covered".
