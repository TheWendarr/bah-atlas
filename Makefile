# BAH Atlas pipeline. Adjust YEAR and the ZCTA file as releases change.
YEAR ?= 2026
PYTHON ?= python3
BAH_ZIP  ?= data/raw/BAH-ASCII-$(YEAR).zip
ZCTA_SHP ?= data/raw/cb_2020_us_zcta520_500k.zip   # geopandas reads the zipped shapefile directly
COMPONENTS_PDF ?= data/raw/dod_bah_rate_components_$(YEAR).pdf
INTERIM  ?= data/interim/bah_$(YEAR)
PROCESSED?= data/processed
BENCH    ?= data/interim/benchmarks_$(YEAR)
METRICS  ?= data/interim/metrics_$(YEAR)
SPATIAL  ?= data/interim/spatial_$(YEAR)
# Neighbours per MHA in the B16 k-nearest-neighbour weights.
KNN_K    ?= 6
ZORI_CSV ?= data/raw/Zip_zori_uc_sfrcondomfr_sm_month.csv
ZHVI_CSV ?= data/raw/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv
SAFMR_XLSX ?= data/raw/fy2026_safmrs_revised.xlsx
PMMS_CSV ?= data/raw/PMMS_history.csv
# Benchmark time window; empty = the BAH calendar year from config/profiles.json.
WINDOW   ?=
WINDOW_ARG = $(if $(WINDOW),--window $(WINDOW),)

.PHONY: all fetch check-config ingest geometry non-mha components tiles basemap \
	benchmarks zori zhvi safmr ownership metrics weights spatial test clean

all: check-config geometry non-mha components tiles benchmarks metrics spatial

# Stage 0: pull every auto-pullable Layer 1 source into data/raw (A2-A7).
fetch:
	$(PYTHON) pipeline/fetch/fetch_sources.py

# Validate the authored config nodes A12 (profiles) and A13 (classification).
check-config:
	$(PYTHON) pipeline/check_config.py

# Stage 1: translate the DTMO BAH ASCII release into tidy CSVs + manifest (A1 -> B1-B4).
ingest: $(BAH_ZIP)
	$(PYTHON) pipeline/ingest/ingest_bah_ascii.py --zip $(BAH_ZIP) --out $(INTERIM)

# Stage 2: dissolve ZCTA polygons up to MHA level using the ingested crosswalk (-> B6).
geometry: ingest
	$(PYTHON) pipeline/geometry/build_mha_geometry.py \
		--crosswalk $(INTERIM)/zip_mha_geo.csv \
		--zcta $(ZCTA_SHP) \
		--out $(PROCESSED)/mha_$(YEAR).gpkg

# County Cost Group and territory-bucket polygons by the same dissolve as B6
# (A2 + B1 -> B28). DoD publishes none, so they are marked non-authoritative and
# kept out of the spatial statistics. Reads B1, so run `make ingest` first.
non-mha:
	$(PYTHON) pipeline/geometry/build_mha_geometry.py --classes ccg,unknown \
		--crosswalk $(INTERIM)/zip_mha.csv \
		--zcta $(ZCTA_SHP) \
		--out $(PROCESSED)/non_mha_$(YEAR).gpkg

# Rent/utilities split per MHA from the DTMO component breakdown PDF (A6 -> B5).
# Cross-checks codes against B3, so run `make ingest` first.
components:
	$(PYTHON) pipeline/ingest/ingest_rate_components.py \
		--pdf $(COMPONENTS_PDF) \
		--out $(INTERIM) \
		--mha-names $(INTERIM)/mha_names.csv

# Tile every area for MapLibre as one layer `areas` keyed on `code` (B6 + B28 -> B7,
# decision D9; docs/data-contract.md section 4). Needs tippecanoe >= 2.17.
# The MHA-only archive this replaced (mha_YYYY.pmtiles) and its manifest are
# removed first, so `make evidence` does not copy a retired B7 manifest.
tiles:
	rm -f $(PROCESSED)/mha_$(YEAR).pmtiles $(PROCESSED)/mha_$(YEAR)_manifest.json
	$(PYTHON) pipeline/tiles/build_mha_pmtiles.py \
		--geojson $(PROCESSED)/mha_$(YEAR).geojson \
		--non-mha $(PROCESSED)/non_mha_$(YEAR).geojson \
		--out $(PROCESSED)/areas_$(YEAR).pmtiles

# Self-hosted basemap cut from a Protomaps daily build (A11). Needs the pmtiles CLI.
# Override with e.g. `MAXZOOM=6 make basemap`; see the script header.
basemap:
	bash pipeline/tiles/build_basemap.sh

# --- 2.3 MHA benchmarks + 2.4 ownership metrics (B8-B11) ---------------------
# Each reads a ZIP-level Layer 1 source and rolls it up to the MHA through the B1
# crosswalk. Needs `make ingest` and `make components` first (B1, B5).
# Override the window with e.g. `make benchmarks WINDOW=2026-01:2026-06`.
benchmarks: zori zhvi safmr ownership

# A3 + B5 -> B8: ZORI at MHA, grossed up to utilities-inclusive.
zori:
	$(PYTHON) pipeline/benchmarks/zillow_to_mha.py --series zori --csv $(ZORI_CSV) \
		--crosswalk $(INTERIM)/zip_mha.csv --rate-components $(INTERIM)/rate_components.csv \
		--out $(BENCH) $(WINDOW_ARG)

# A4 -> B9: ZHVI at MHA.
zhvi:
	$(PYTHON) pipeline/benchmarks/zillow_to_mha.py --series zhvi --csv $(ZHVI_CSV) \
		--crosswalk $(INTERIM)/zip_mha.csv --out $(BENCH) $(WINDOW_ARG)

# A5 -> B10: 0-4 bedroom SAFMRs at MHA.
safmr:
	$(PYTHON) pipeline/benchmarks/safmr_to_mha.py --xlsx $(SAFMR_XLSX) \
		--crosswalk $(INTERIM)/zip_mha.csv --out $(BENCH)

# A7 + B9 (+ B8 utilities) -> B11: monthly ownership cost; parameters in config/ownership.json.
ownership: zori zhvi
	$(PYTHON) pipeline/benchmarks/ownership_cost.py --zhvi $(BENCH)/mha_zhvi.csv \
		--zori $(BENCH)/mha_zori.csv --pmms $(PMMS_CSV) --out $(BENCH) $(WINDOW_ARG)

# --- 2.5 computed metrics (B12-B15) ------------------------------------------
# Adequacy ratio and gap vs the statutory design, coverage ratio, flat-95% sensitivity
# gap, and dollar surplus for every A12 profile
# x real MHA: rent (B8, with the B10 SAFMR cross-check) and buy (B11).
# Needs `make benchmarks` first; stops if B8 and B9 cover different months.
metrics:
	$(PYTHON) pipeline/metrics/coverage_metrics.py --bah-rates $(INTERIM)/bah_rates.csv \
		--zori $(BENCH)/mha_zori.csv --safmr $(BENCH)/mha_safmr.csv \
		--ownership $(BENCH)/mha_ownership.csv --out $(METRICS)

# --- 2.6 spatial statistics (B16-B18) ----------------------------------------
# B6 -> B16: k-nearest-neighbour weights for the CONUS MHAs (AK, HI excluded), with
# queen contiguity built alongside as a diagnostic. Needs `make geometry` first.
weights:
	$(PYTHON) pipeline/spatial/build_weights.py --geometry $(PROCESSED)/mha_$(YEAR).gpkg \
		--k $(KNN_K) --out $(SPATIAL)

# B12/B14 + B16 -> B17, B18: global Moran's I, LISA and Getis-Ord Gi* for every A12
# profile x rent/buy x adequacy_gap (primary) / flat95_gap (sensitivity), plus a LISA
# cluster map of the primary test. Needs `make metrics` first. Reproducible: fixed
# seed; override with e.g. `make spatial PERMUTATIONS=999` for a quick run.
PERMUTATIONS ?= 9999
SEED ?= 2026
spatial: weights
	$(PYTHON) pipeline/spatial/spatial_stats.py --geometry $(PROCESSED)/mha_$(YEAR).gpkg \
		--weights-manifest $(SPATIAL)/weights_manifest.json \
		--rent-metrics $(METRICS)/mha_rent_metrics.csv --buy-metrics $(METRICS)/mha_buy_metrics.csv \
		--permutations $(PERMUTATIONS) --seed $(SEED) --out $(SPATIAL)

# Unit tests against synthetic fixtures (no downloads needed).
test:
	$(PYTHON) -m unittest discover -s tests -v

clean:
	rm -rf $(SPATIAL) $(METRICS) $(BENCH) $(INTERIM) $(PROCESSED)/mha_$(YEAR).gpkg $(PROCESSED)/mha_$(YEAR).geojson \
		$(PROCESSED)/mha_$(YEAR).pmtiles $(PROCESSED)/mha_$(YEAR)_manifest.json \
		$(PROCESSED)/mha_$(YEAR)_geometry_manifest.json \
		$(PROCESSED)/non_mha_$(YEAR).gpkg $(PROCESSED)/non_mha_$(YEAR).geojson \
		$(PROCESSED)/non_mha_$(YEAR)_geometry_manifest.json \
		$(PROCESSED)/areas_$(YEAR).pmtiles $(PROCESSED)/areas_$(YEAR)_manifest.json

# --- Project tracking (living WBS) -------------------------------------------
# Source of truth: docs/wbs/nodes.csv and docs/wbs/milestones.csv.
.PHONY: wbs wbs-week wbs-show start done scrap wbs-sync wbs-sync-dry evidence verify hooks

# Mark nodes in progress / complete / scrapped and regenerate docs/WBS.md in one step.
#   make start N="A3 A6"     make done N="A3-A6 B5"     make scrap N=B26     make wbs-show N=B7
start:
	$(PYTHON) tools/wbs.py start $(N)

done:
	$(PYTHON) tools/wbs.py done $(N)

scrap:
	$(PYTHON) tools/wbs.py scrap $(N)

wbs-show:
	$(PYTHON) tools/wbs.py show $(N)

# Regenerate docs/WBS.md and the progress index from the CSVs.
wbs:
	$(PYTHON) tools/wbs_render.py

# Regenerate docs/WBS.md and docs/progress/README.md, and scaffold this week's
# progress note on the five-part template. The milestone is chosen by date;
# override with e.g. `make wbs-week M=M5`.
wbs-week:
	$(PYTHON) tools/wbs_render.py --new-entry $(if $(M),--milestone $(M),)

# Copy pipeline manifests and the unit-test result into docs/evidence/ so
# progress notes can link to results. Run after the pipeline, before wbs-week.
evidence:
	$(PYTHON) tools/collect_evidence.py

# Check every recorded SHA-256: evidence copies, config hashes, the hash chain
# between manifests, and (where data/ holds pipeline output) the live files.
verify:
	$(PYTHON) tools/verify_hashes.py

# Turn on the commit-message check (subject must name a node or milestone id).
hooks:
	git config core.hooksPath .githooks
	@echo "commit-msg hook enabled (.githooks/commit-msg)"

# Mirror milestones and node issues to GitHub (requires an authenticated gh CLI).
wbs-sync:
	$(PYTHON) tools/wbs_sync_github.py

# Show what wbs-sync would change on GitHub without changing anything.
wbs-sync-dry:
	$(PYTHON) tools/wbs_sync_github.py --dry-run
