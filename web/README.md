# Web

The BAH Atlas static map (Layer 3): MapLibre GL JS, vanilla ES modules, no framework.
It reads only `delivery/<year>/` and follows the
[data contract](../docs/data-contract.md).

| Command | What it does |
|---|---|
| `make web-deps` | Installs the pinned packages from `package-lock.json` |
| `make web-dev` | Builds with the tiles copied in and serves http://localhost:8000 |
| `make web-build` | Builds the production site in `web/dist` |
| `make web-test` | Formula parity on all 218,316 views, the class rule and the contract gate |
| `make web-e2e` | The built site in a real browser (first run: `cd web && npx playwright install chromium`) |
| `make site-check` | The deployed site against `web/dist`: files, types and security headers, allowing Cloudflare's Bot Fight Mode script and nothing else (D33) |
| `make web-e2e-live` | The same browser tests against the deployed site and the real tile host |

`python -m http.server` cannot run this site, because it ignores the HTTP range
requests PMTiles depends on. `make web-dev` serves ranges correctly.

## Layout

| Path | Holds |
|---|---|
| `build.mjs` | Checks the delivery against `SHA256SUMS`, bundles the app, writes `dist/` and the security headers |
| `site.config.json` | The year and the two public hostnames |
| `src/contract.js` | Loads the delivered files; refuses to render if they do not share one build |
| `src/grid.js` | The ICD 5b.4 formula, compared in tests with `contract.grid_view` |
| `src/classify.js` | The ICD section 6 class rule |
| `src/map.js` | MapLibre setup, area layers and the value join |

The two tile archives live on Cloudflare R2, and the site and its JSON on Cloudflare
Pages. A push to `main` that touches the site runs `.github/workflows/web.yml`: unit
and browser tests, then deployment and the two live checks. Tiles are uploaded by hand
(`make host-check` tests them), because they change only at a deliberate delivery.

Wording about the data comes from `ui_metadata_<year>.json`, never from this folder.
