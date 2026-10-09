# BAH Atlas

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
├── config/          authored config: profiles.json (A12), classification.json (A13)
├── pipeline/
│   ├── fetch/       Layer 1 source fetcher with provenance manifest
│   ├── ingest/      endpoint translators: raw release -> tidy CSVs + manifest
│   ├── geometry/    spatial builders: crosswalk + ZCTA -> MHA polygons
│   └── tiles/       PMTiles builders: MHA tiles (B7) and basemap cutout (A11)
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

make fetch          # download Layer 1 sources into data/raw (A2-A7) with checksums
make check-config   # validate config/profiles.json and config/classification.json
make geometry       # BAH ASCII -> tidy CSVs (B1-B4) -> MHA polygons (B6)
make components     # rent/utilities split per MHA (A6 -> B5)
make tiles          # MHA PMTiles for MapLibre (B6 -> B7); needs tippecanoe
make basemap        # basemap cutout from a Protomaps build (A11); needs the pmtiles CLI
```

`make all` runs check-config, geometry, components, and tiles in order. Each
script prints its own usage with `--help`.

## Status

See the **[Work Breakdown Structure](docs/WBS.md)** for current milestone and
node status, and the **[weekly progress log](docs/progress/)** for narrative
updates.

### Updating project status

```bash
make start N="B8"          # mark nodes in progress
make done N="A3-A6 B5"     # mark nodes complete today (ranges allowed)
make wbs-show              # print every node's status
make wbs-week              # start this week's log entry in docs/progress/
# write the narrative in docs/progress/<date>.md, then commit and push
make wbs-sync              # optional: mirror milestones and issues to GitHub (gh CLI)
```

`start` and `done` rewrite `docs/wbs/nodes.csv` and regenerate `docs/WBS.md`, so a
status change is one command and one small diff.

## License

MIT — see `LICENSE`.
