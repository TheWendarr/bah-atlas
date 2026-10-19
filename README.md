# BAH Atlas

> **Project status — live**
>
> | | |
> |---|---|
> | 📋 **[Work Breakdown Structure](docs/WBS.md)** | Milestones, due dates, every node's status, and the nodal map |
> | 📝 **[Progress notes](docs/progress/)** | One note per week on a fixed five-part template, tied to a milestone, with linked evidence; the folder index shows each milestone's status and latest note |
> | 🎯 **[GitHub milestones](https://github.com/TheWendarr/bah-atlas/milestones)** | The same milestones as progress bars, mirrored from the WBS |
> | 🧭 **[M6 plan](docs/plans/m6-plan.md)** | The Layer 2 → Layer 3 handoff: decisions taken, decisions open, and how each M6 node will be built |
> | 📐 **[Data contract (ICD)](docs/data-contract.md)** | Every file Layer 3 receives from the pipeline: fields, codes, rules for missing values, and the checks the handoff must pass |
>
> Status is kept in [`docs/wbs/nodes.csv`](docs/wbs/nodes.csv); `make wbs` regenerates the WBS page from it.

An open, reproducible atlas of how far the U.S. military **Basic Allowance for
Housing (BAH)** stretches against real local housing costs — showing where the
allowance meets its statutory coverage target and where it falls short, mapped
across every Military Housing Area (MHA).

By statute (37 U.S.C. 403(b)(3)), BAH equals the local cost of adequate housing
minus a member cost share of 5% of the *national* average cost for the pay grade.
That share is the same dollars everywhere, so BAH pays roughly 95% of local cost
on average, more than 95% in expensive areas and less in cheap ones. This project
measures BAH against that design using an independent housing-cost benchmark and
characterizes where the gaps cluster in space.

## Research question

> To what degree do 2026 BAH rates meet their statutory design (the local cost
> of adequate housing less a member cost share fixed at 5% of the national
> average cost) when measured against an independent housing-cost benchmark, and
> are the resulting adequacy gaps spatially clustered across U.S. Military
> Housing Areas rather than randomly distributed?

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
- **Rent/utilities split and member cost share** — DTMO BAH Rate Component Breakdown and out-of-pocket table
- **Mortgage rate** — Freddie Mac Primary Mortgage Market Survey (PMMS)
- **Property tax and population density** — U.S. Census American Community Survey (ACS) 5-year, ZCTA level
- **Homeowners insurance** — U.S. Treasury Federal Insurance Office (FIO) ZIP-level premiums, 2022

The full register, with licences and caveats, is [`docs/SOURCES.md`](docs/SOURCES.md).

## Repository layout

```
bah-atlas/
├── data/
│   ├── raw/         vendor artifacts as downloaded; the U.S. Government ones are committed, third-party data is gitignored
│   ├── interim/     tidy parsed outputs (gitignored)
│   └── processed/   final web-ready geometry/tiles (gitignored)
├── config/          authored config, values only: profiles.json (A12), classification.json (A13), ownership.json (B11)
├── pipeline/
│   ├── fetch/       Layer 1 source fetcher with provenance manifest
│   ├── ingest/      endpoint translators: raw release -> tidy CSVs + manifest (B1-B5)
│   ├── geometry/    spatial builders: crosswalk + ZCTA -> MHA polygons (B6)
│   ├── benchmarks/  ZIP-level benchmarks rolled up to the MHA (B8-B11)
│   ├── metrics/     coverage and adequacy metrics (B12-B15)
│   ├── spatial/     spatial weights, Moran's I, LISA, Gi* (B16-B18), spatial regression (B19)
│   ├── tiles/       PMTiles builders: area tiles (B7) and basemap cutout (A11)
│   ├── handoff/     the Layer 2 -> Layer 3 files to the data contract (B20-B22, B27)
│   └── qa/          QA / validation report (B23)
├── delivery/        the validated handoff, added only by `make deliver` (decision D10)
├── web/             MapLibre GL JS frontend (Layer 3, not started)
├── docs/            research framing, data dictionary, data contract (ICD), configuration reference, attribution
│   ├── WBS.md       live work breakdown structure (generated)
│   ├── wbs/         nodes.csv + milestones.csv — project status source of truth
│   ├── progress/    progress notes on the five-part template, with index
│   ├── plans/       milestone plans (M6: the Layer 2 -> Layer 3 handoff)
│   └── evidence/    pipeline manifests and test results linked from the notes
├── tools/           project tooling (WBS renderer, progress notes, evidence, GitHub sync)
└── tests/           unit tests on synthetic fixtures
```

## Quickstart

To rebuild everything on another machine, step by step (requirements, where each source
file goes, how to check the result), follow [`docs/REPRODUCING.md`](docs/REPRODUCING.md).

```bash
pip install -r requirements.txt

make fetch          # download Layer 1 sources into data/raw (A2-A9) with checksums;
                    # the A9 Census query needs CENSUS_API_KEY set (free key, see docs/SOURCES.md)
make check-config   # validate config/profiles.json and config/classification.json (see docs/configuration.md)
make geometry       # BAH ASCII -> tidy CSVs (B1-B4) -> MHA polygons (B6)
make components     # rent/utilities split per MHA (A6 -> B5)
make non-mha        # County Cost Group and territory polygons (B1 -> B28), non-authoritative
make tiles          # one area PMTiles layer for MapLibre (B6 + B28 -> B7); needs tippecanoe
make basemap        # basemap cutout from a Protomaps build (A11); needs the pmtiles CLI
make benchmarks     # ZORI, ZHVI, SAFMR, A8 tax and insurance, ownership cost at the MHA (B8-B11)
make metrics        # adequacy and coverage metrics (B12-B15)
make spatial        # spatial weights, Moran's I, LISA, Gi* (B16-B18)
make regression     # population density (B24) and the H2 spatial regression (B19)
make test           # unit tests on synthetic fixtures
make handoff        # the Layer 3 handoff files + SHA256SUMS in data/processed/handoff, validated
make evidence       # copy manifests and test results into docs/evidence/
make verify         # check every recorded SHA-256 against configs, evidence and data
make qa             # QA / validation report (B23) in data/processed/qa
make layer2         # all of the above from data/raw (no fetch), end to end, with evidence and checks
make deliver-check  # the six D10 gates; `make deliver` copies the handoff into delivery/ when they pass
```

`make all` runs check-config, geometry, non-mha, components, tiles, benchmarks, metrics,
and spatial in order. Each script prints its own usage with `--help`.

## Status

See the **[Work Breakdown Structure](docs/WBS.md)** for current milestone and
node status, and the **[weekly progress log](docs/progress/)** for narrative
updates.

### Updating project status

```bash
make start N="B8"          # mark nodes in progress
make done N="A3-A6 B5"     # mark nodes complete today (ranges allowed)
make scrap N="B26"         # mark nodes scrapped (id and history kept)
make wbs-show              # print every node's status
make evidence && make verify   # refresh docs/evidence/ and prove its hashes agree
make wbs-week              # scaffold this week's progress note in docs/progress/
# fill in the author parts of docs/progress/<date>.md, then commit and push
make wbs-sync              # optional: mirror milestones and issues to GitHub (gh CLI)
```

`start` and `done` rewrite `docs/wbs/nodes.csv` and regenerate `docs/WBS.md`, so a
status change is one command and one small diff.

## License

MIT — see `LICENSE`.
