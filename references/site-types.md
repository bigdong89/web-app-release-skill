# Site types and hosting adjustments

Calibrate the audit so a docs site isn't graded on checkout flows and a SaaS
isn't failed for not having a blog sitemap.

## Detecting the site type

Signals, in order: `package.json` deps and scripts; route tree (auth pages,
cart, docs layout); robots/sitemap shape; user's description. When signals
conflict, ask the user which type to grade against.

Types: **marketing** · **docs** · **saas-app** (auth-gated product) ·
**e-commerce** · **hybrid** (public + app routes).

## Domain weight matrix

`F` = full audit · `L` = lite (script layer + spot checks) · `—` = skip

| Domain | marketing | docs | saas-app | e-commerce | hybrid |
|---|---|---|---|---|---|
| 1 Build hygiene | L | L | F | F | F (app) / L (public) |
| 2 HTTP & infra | F | F | F | F | F |
| 3 SEO | F | F | L (public routes only) | F + product schema | split by route |
| 4 GEO | F | F | L | L | public routes |
| 5 Performance | F | F | F (app shell) | F | F |
| 6 Accessibility | F | F | F | F | F |
| 7 Functional QA | L | L | F | F (checkout!) | F on app routes |
| 8 Privacy/compliance | L (if tracking) | — | F | F | F |
| 9 Release ops | L | — | F | F | F |

Domain 8 note: the GDPR applicability triage (domains.md §8, step 0) always
runs regardless of weight — it is a recorded decision, not an audit pass; the
weight applies to the remaining §8 items. `docs` skips the rest, but a privacy
policy link check (PRV-001) is still cheap courtesy on any public site.

For `saas-app`/`hybrid`: audit public routes with the full SEO/GEO lens and
app routes with build/HTTP/functional/ops. `key_routes` in
`.release-check.yml` should split them (e.g. `public: ["/", "/pricing"]`,
`app: ["/dashboard"]` with a login cookie).

## Hosting matrix (false-positive guard)

Some hosts don't let you set arbitrary response headers on their subdomains.
When the target host matches, downgrade script `fail` on security headers
(SEC-001..005) to `warn` and say why in the report:

| Host pattern | Limitation | Action |
|---|---|---|
| `*.github.io`, `*.gitlab.io` | No custom response headers | Warn + note "platform-limited" |
| `*.vercel.app`, `*.netlify.app`, `*.pages.dev` | Configurable **via repo config** (`vercel.json`, `netlify.toml`, `_headers`) | Before failing, check the repo for the config file; missing both = fail |
| Custom domain on any host | No limitation | Normal pass/fail |

`release_audit.py` auto-downgrades `github.io`/`gitlab.io`; the vercel/netlify
repo-config check is yours (judgment) — do it in Phase 0 recon.

## Context: preview vs production

`--context preview` downgrades TLS/HSTS/header misses from fail to warn so a
pre-production URL can be audited without noise. Judgment domains (compliance,
ops) still apply in full for production-bound releases.
