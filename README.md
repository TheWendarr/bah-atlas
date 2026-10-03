# BAH Atlas

*Working title — see naming note in project docs.*

> **Project status — live**
>
> | | |
> |---|---|
> | 📋 **[Work Breakdown Structure](docs/WBS.md)** | Milestones, due dates, every node's status, and the nodal map |
> | 📝 **[Weekly progress log](docs/progress/)** | What was done, what is next, setbacks and changes, one entry per week |
> | 🎯 **[GitHub milestones](https://github.com/TheWendarr/bah-atlas/milestones)** | The same milestones as progress bars, mirrored from the WBS |
>
> Status is kept in [`docs/wbs/nodes.csv`](docs/wbs/nodes.csv); `make wbs` regenerates the WBS page from it.

An open, reproducible atlas of how far the U.S. military **Basic Allowance for
Housing (BAH)** stretches against real local housing costs — showing where the
allowance meets its statutory coverage target and where it falls short, mapped
across every Military Housing Area (MHA).

BAH is designed to cover roughly 95% of local housing costs (a deliberate ~5%
member cost-share). This project measures realized coverage against an
independent housing-cost benchmark and characterizes where the gaps cluster in
space.

## Research question

> To what degree do BAH rates achieve their statutory coverage target relative
> to an independent housing-cost benchmark, and are the resulting adequacy gaps
> spatially clustered across U.S. Military Housing Areas rather than randomly
> distributed?

See `docs/research-proposal.md` for the full framing, method, and scope.

## How it works

A Python offline pipeline turns public data endpoints into static, web-ready
files; a MapLibre GL JS frontend renders them from a CDN. No live API calls at
request time.

```
data endpoint --> ingest (tidy CSVs) --> geometry (MHA polygons) --> tiles/JSON --> map
```

## Data sources

Each layer is attributed to its source:

- **BAH rates & ZIP-to-MHA crosswalk** — DoD Defense Travel Management Office (DTMO)
- **MHA geometry** — synthesized from U.S. Census ZIP Code Tabulation Areas (ZCTAs)
- **Rent benchmark** — Zillow Observed Rent Index (ZORI)
- **Home-value benchmark** — Zillow Home Value Index (ZHVI)
- **Affordability reference** — HUD Fair Market Rents (FMR / SAFMR)
- **Income / price context** — U.S. Census ACS, BEA Regional Price Parities (RPP)

## Repository layout

```
bah-atlas/
├── data/
│   ├── raw/         vendor artifacts as downloaded (gitignored)
│   ├── interim/     tidy parsed outputs (gitignored)
│   └── processed/   final web-ready geometry/tiles (gitignored)
├── pipeline/
│   ├── ingest/      endpoint translators: raw release -> tidy CSVs + manifest
│   └── geometry/    spatial builders: crosswalk + ZCTA -> MHA polygons
├── web/             MapLibre GL JS frontend (later)
├── docs/            research framing, data dictionary, attribution
│   ├── WBS.md       live work breakdown structure (generated)
│   ├── wbs/         nodes.csv + milestones.csv — project status source of truth
│   └── progress/    weekly progress log
├── tools/           project tooling (WBS renderer, GitHub milestone sync)
└── tests/
```

## Quickstart

```bash
pip install -r requirements.txt

# Stage 1 — ingest the DTMO BAH ASCII release into tidy CSVs + manifest
python pipeline/ingest/ingest_bah_ascii.py \
    --zip data/raw/BAH-ASCII-2026.zip \
    --out data/interim/bah_2026

# Stage 2 — build MHA polygons (needs a Census ZCTA cartographic boundary file)
python pipeline/geometry/build_mha_geometry.py \
    --crosswalk data/interim/bah_2026/zip_mha_geo.csv \
    --zcta data/raw/cb_2020_us_zcta520_500k.shp \
    --out data/processed/mha_2026.gpkg
```

Or run both stages with `make` (see `Makefile`).

## Status

See the **[Work Breakdown Structure](docs/WBS.md)** for current milestone and
node status, and the **[weekly progress log](docs/progress/)** for narrative
updates.

### Updating project status

```bash
# 1. Edit docs/wbs/nodes.csv: set status (complete | in_progress | not_started)
#    and, when a node finishes, its completed date (YYYY-MM-DD).
# 2. Regenerate the WBS page and scaffold this week's log entry:
make wbs-week
# 3. Write the narrative in docs/progress/<today>.md, then commit and push.
# 4. Optional: mirror milestones and node issues to GitHub (needs the gh CLI):
make wbs-sync
```

## License

MIT — see `LICENSE`.
