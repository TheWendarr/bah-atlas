# Reproducing BAH Atlas on another machine

How to rebuild Layers 1 and 2 of BAH Atlas from a fresh clone: the source files, the
pipeline, the Layer 3 handoff files and the QA report. Follow the steps in order.
Layer 3 (the web map) is not built yet and is not covered here.

Tracker: [WBS](WBS.md) · sources and licences: [SOURCES.md](SOURCES.md) · what the
handoff files contain: [data contract](data-contract.md) · table layouts:
[data dictionary](data-dictionary.md)

---

## 1. What you will get

`make layer2` rebuilds every Layer 2 product from the files in `data/raw/`:

- MHA, County Cost Group and territory polygons, and one vector tile archive (B6, B28, B7)
- the rent and home-value benchmarks, ownership cost and adequacy metrics for every
  MHA (B8–B15)
- the spatial statistics (B16–B18), population density (B24) and the H2 regression (B19)
- the five handoff files for Layer 3, validated against the data contract (B20–B22, B27)
- the QA report (B23), which re-checks every recorded hash and traces three MHAs by hand

Two levels of replication are possible:

| Level | What it needs | Result |
|---|---|---|
| **Exact** | Byte-identical copies of all ten source files (section 4) | The published 2026 numbers, digit for digit |
| **Current data** | The government files in the repository plus fresh downloads of the three third-party files | The same pipeline and checks; numbers differ slightly, because Zillow and Freddie Mac republish their files at the same URL |

---

## 2. Requirements

| Tool | Version | Needed for | Where to get it |
|---|---|---|---|
| Linux or macOS | — | everything (on Windows, use WSL 2 with Ubuntu) | [WSL install guide](https://learn.microsoft.com/windows/wsl/install) |
| Git | any recent | cloning | https://git-scm.com/downloads |
| GNU Make | 3.81 or newer | every `make` command | preinstalled on Linux; macOS: `xcode-select --install` |
| Python | 3.11 or newer (developed on 3.14, tested on 3.13) | the pipeline | https://www.python.org/downloads/ |
| tippecanoe | **2.17 or newer** (2026 build: 2.82.0) | the area tiles, B7 (`make tiles`, part of `make all`) | https://github.com/felt/tippecanoe |
| `sha256sum` | GNU coreutils | `make handoff` | preinstalled on Linux; macOS: `brew install coreutils` if missing |
| pmtiles CLI | optional | the basemap only (`make basemap`, Layer 3) | https://github.com/protomaps/go-pmtiles/releases |
| GitHub CLI `gh` | optional | mirroring the tracker to GitHub (`make wbs-sync`) | https://cli.github.com |

Disk: 1–2 GB free (sources 221 MB; intermediate files and tiles the rest).
A Census API key is **not** needed: the Census query result (A9) is in the repository.

### Install tippecanoe

```bash
# macOS
brew install tippecanoe

# Fedora
sudo dnf install gcc-c++ make sqlite-devel zlib-devel git
# Debian / Ubuntu / WSL
sudo apt install build-essential libsqlite3-dev zlib1g-dev git

# then, on Linux, build from source:
git clone https://github.com/felt/tippecanoe.git ~/src/tippecanoe
cd ~/src/tippecanoe && make -j && sudo make install
tippecanoe --version          # must print 2.17 or newer
```

---

## 3. Clone and set up Python

```bash
git clone https://github.com/TheWendarr/bah-atlas.git ~/bah-atlas
cd ~/bah-atlas

python3 -m venv .venv                 # .venv/ is gitignored
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt       # pandas, geopandas, pypdf, openpyxl, libpysal, esda, spreg, matplotlib

make test                             # unit tests on synthetic data; should end with "OK"
```

The clone is about 90 MB, mostly the seven government source files in `data/raw/`.
Every later command is run from the repository folder (`~/bah-atlas` here) with the
virtual environment active.

---

## 4. Put the source files in `data/raw/`

All ten Layer 1 files live in `data/raw/`. Seven are already there; three must be
downloaded.

### Already in the repository (U.S. Government works)

| Node | File | Bytes | SHA-256 |
|---|---|---|---|
| A1 | `BAH-ASCII-2026.zip` | 302,657 | `5446fed831e125c23cc6a407dcde4cae541f108e90ac852aaadeec0aa11e515f` |
| A2 | `cb_2020_us_zcta520_500k.zip` | 66,655,314 | `c69a4ede8aebebfc7ed3a98a9075c6aaa1b75d514a129bc5c662fd806d2f3d17` |
| A5 | `fy2026_safmrs_revised.xlsx` | 4,382,259 | `35e26f33181adcfd2b5b457f7824fe2880e65be18aec2805766e39b5eaf3e28f` |
| A6 | `dod_bah_rate_components_2026.pdf` | 208,266 | `a0cbf7f4dad787ffbb3605c151f69c61ee4e2dd7bb39e1bcff3646bed8b69800` |
| A8 | `Supporting_Underlying_Metrics_and_Disclaimer_for_Analyses_of_US_Homeowners_Insurance_Markets_2018-2022.xlsx` | 14,892,818 | `99ff8f67d930232d375d3813ffbacacd2a4a8d932d89c81fd8b17b5a6343672e` |
| A9 | `acs5_2024_zcta.json` | 1,219,849 | `51455fa2249e07c0107b8972a844bbf725c52c062344b4af90f8f48129b70f30` |
| A12 | `2026-BAH_OOP_Amounts.pdf` | 266,626 | `375ff25e5e8d0eb5d81f5d427534a672310c35bb745d40b31ceb7ba3c72520c3` |

### Downloaded by `make fetch` (third-party data, not redistributed)

| Node | File | Download URL | SHA-256 of the copy the 2026 build used |
|---|---|---|---|
| A3 | `Zip_zori_uc_sfrcondomfr_sm_month.csv` | https://files.zillowstatic.com/research/public_csvs/zori/Zip_zori_uc_sfrcondomfr_sm_month.csv | `357c4544a4691608bbd20ff9941d4a112be54056fcae652de9d7cf41b601ac42` (retrieved 2026-09-07) |
| A4 | `Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv` | https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv | `50dce14cddd4e3cf27da5b84708fa79dd85e982bd8831c4c12e04f6b7c967719` (retrieved 2026-09-07) |
| A7 | `PMMS_history.csv` | https://www.freddiemac.com/pmms/docs/PMMS_history.csv | `d91ae5ab2fea079a6111cf5eb835cea1734052d2a08b342f2d8c79c92bb3dc8f` (retrieved 2026-10-03) |

Zillow data must be attributed to Zillow, and PMMS data to Freddie Mac
([SOURCES.md](SOURCES.md) has the terms).

### Commands

```bash
# 1. Start from the provenance record of the 2026 build, so the seven committed files
#    keep their original retrieval dates (data/raw/fetch_manifest.json is gitignored).
cp docs/evidence/fetch_manifest.json data/raw/fetch_manifest.json

# 2. Download the three third-party files; the seven committed ones are checked, not re-downloaded.
make fetch

# 3. Compare every file with the 2026 build's copy.
sha256sum data/raw/*.zip data/raw/*.csv data/raw/*.xlsx data/raw/*.json data/raw/*.pdf
```

The seven government files must match the first table exactly. For the three
third-party files:

- **All three match:** you have the exact inputs; continue to section 5.
- **Any differs:** Zillow and Freddie Mac have published a newer file since. The build
  still runs and passes every check, but it describes the newer data. For an exact
  replication, put byte-identical copies of those files in `data/raw/` under the same
  names before section 5; `make fetch` then records them without downloading.

If a provider has moved a file and `make fetch` fails, the landing pages in
[SOURCES.md](SOURCES.md) lead to the current location; save the file under the name
above. Do not use `make fetch --force` in an exact replication: it replaces files.

---

## 5. Build Layers 1 and 2

```bash
make layer2
```

This runs, in order: `make all` (configs, ingest, geometry, tiles, benchmarks, metrics,
spatial statistics), `make regression` (B24 and B19), `make handoff` (the five Layer 3
files, validated), `make evidence` and `make verify`, `make qa` (B23), and
`make evidence` and `make verify` again. It stops at the first failure.

The slowest step is the spatial statistics: 99,999 permutations per test (the
recorded run). For a quick trial run, `make layer2 PERMUTATIONS=999` finishes much
faster, but its p-values and cluster counts are not the published ones.

`make layer2` rewrites the manifest copies in `docs/evidence/`. In an exact
replication `git diff docs/evidence` should show only timestamps, run times, the git
commit, software versions and the test log; any changed SHA-256 or count means an input differs.

---

## 6. Check the result

```bash
make verify                                        # every recorded SHA-256 agrees
less data/processed/qa/qa_2026.md                  # the QA report: verdict at the top
cat data/processed/handoff/SHA256SUMS              # the five handoff files
```

With exact inputs:

- the QA report's verdict is **PASS**, with three NOTE rows (one value that changes
  class through rounding, the ambiguous B19 model form, the B19 sample difference)
- the primary H1 test (E-5 with dependents, rent mode) gives **Moran's I = 0.1515**,
  pseudo p = 0.00001, n = 283, with 20 HH, 6 LL, 5 HL and 7 LH clusters and 2
  FDR-significant MHAs (`data/interim/spatial_2026/spatial_stats_manifest.json`)
- the B19 primary run models **201** MHAs and the 3-year run **255**
  (`data/interim/spatial_2026/regression_manifest.json`)
- the payload covers **339** areas: 299 MHAs, 39 County Cost Groups, 1 territory bucket

The handoff files themselves are not byte-identical between machines: the build
manifest (B22) records the build time, the git commit and software versions, and the
other three JSON files carry its SHA-256 as their `build_id`. The values inside them
are identical with exact inputs; `make qa` checks every value against its source table.

---

## 7. Where every file is stored

```
bah-atlas/
├── config/                       authored settings (committed): profiles.json (A12), classification.json
│                                 and ui_text.json (A13), ownership.json (B11)
├── data/
│   ├── raw/                      Layer 1 sources (section 4); government files committed, third-party
│   │                             files and fetch_manifest.json gitignored
│   ├── interim/                  gitignored, rebuilt by make
│   │   ├── bah_2026/             B1–B5: zip_mha.csv, zip_mha_geo.csv, mha_names.csv, bah_rates.csv,
│   │   │                         rate_components.csv, manifests
│   │   ├── benchmarks_2026/      B8–B11 and A8: mha_zori.csv, mha_zhvi.csv, mha_safmr.csv,
│   │   │                         mha_tax_insurance.csv, mha_ownership.csv, ZIP-level companions
│   │   ├── metrics_2026/         B12–B15: mha_rent_metrics.csv, mha_buy_metrics.csv
│   │   ├── spatial_2026/         B16–B19: weights, mha_spatial_stats.csv, LISA map, mha_regression.csv
│   │   └── context_2026/         B24: mha_density.csv
│   └── processed/                gitignored, rebuilt by make
│       ├── mha_2026.gpkg/.geojson, non_mha_2026.gpkg/.geojson   B6, B28 polygons
│       ├── areas_2026.pmtiles    B7 area tiles
│       ├── handoff/              the five Layer 3 files + SHA256SUMS (make handoff)
│       └── qa/                   qa_2026.md and its manifest (make qa)
├── delivery/2026/                the validated handoff, added only by make deliver (decision D10)
├── docs/                         documentation; docs/evidence/ holds the committed manifest copies
├── pipeline/                     the pipeline code, by stage (README inside)
├── tools/                        tracker, evidence, hash checks, delivery
└── tests/                        unit tests on synthetic fixtures (make test)
```

Paths are fixed by the `Makefile` (`YEAR ?= 2026`); every stage writes a manifest
beside its outputs with the SHA-256 of what it read and wrote, which is how
`make verify` proves the chain from `data/raw/` to the handoff.

---

## 8. Common problems

| Symptom | Cause and fix |
|---|---|
| `make tiles` stops: "is tippecanoe older than 2.17?" | Install a newer tippecanoe (section 2). |
| `make handoff` stops: `sha256sum: command not found` | macOS without GNU coreutils: `brew install coreutils`. |
| `make fetch` reports A3, A4 or A7 as FAIL | The provider moved or blocked the file. Download it in a browser from the landing page in SOURCES.md and save it under the exact name in section 4. |
| `make verify`, run on its own before `make layer2`, reports evidence out of date | Expected when a downloaded file differs from the 2026 copy, or when step 1 of section 4 was skipped. `make layer2` refreshes `docs/evidence/` from your build and then passes. |
| B8 stops: window holds too few months | The ZORI file has no 2026 months; you have a very old copy. |
| A `make` step fails part-way | Fix the cause and rerun `make layer2`; every stage overwrites its own outputs. |

---

*AI-assistance disclosure: Claude (Anthropic) drafted this guide from the repository
for the author's review.*
