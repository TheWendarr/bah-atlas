# BAH Atlas pipeline. Adjust YEAR and the ZCTA file as releases change.
YEAR ?= 2026
PYTHON ?= python3
BAH_ZIP  ?= data/raw/BAH-ASCII-$(YEAR).zip
ZCTA_SHP ?= data/raw/cb_2020_us_zcta520_500k.zip   # geopandas reads the zipped shapefile directly
COMPONENTS_PDF ?= data/raw/dod_bah_rate_components_$(YEAR).pdf
INTERIM  ?= data/interim/bah_$(YEAR)
PROCESSED?= data/processed

.PHONY: all fetch check-config ingest geometry components tiles basemap clean

all: check-config geometry components tiles

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

# Rent/utilities split per MHA from the DTMO component breakdown PDF (A6 -> B5).
# Cross-checks codes against B3, so run `make ingest` first.
components:
	$(PYTHON) pipeline/ingest/ingest_rate_components.py \
		--pdf $(COMPONENTS_PDF) \
		--out $(INTERIM) \
		--mha-names $(INTERIM)/mha_names.csv

# Tile the MHA polygons for MapLibre (B6 -> B7). Needs tippecanoe >= 2.17.
tiles:
	$(PYTHON) pipeline/tiles/build_mha_pmtiles.py \
		--geojson $(PROCESSED)/mha_$(YEAR).geojson \
		--out $(PROCESSED)/mha_$(YEAR).pmtiles

# Self-hosted basemap cut from a Protomaps daily build (A11). Needs the pmtiles CLI.
# Override with e.g. `MAXZOOM=6 make basemap`; see the script header.
basemap:
	bash pipeline/tiles/build_basemap.sh

clean:
	rm -rf $(INTERIM) $(PROCESSED)/mha_$(YEAR).gpkg $(PROCESSED)/mha_$(YEAR).geojson \
		$(PROCESSED)/mha_$(YEAR).pmtiles $(PROCESSED)/mha_$(YEAR)_manifest.json

# --- Project tracking (living WBS) -------------------------------------------
# Source of truth: docs/wbs/nodes.csv and docs/wbs/milestones.csv.
.PHONY: wbs wbs-week wbs-show start done wbs-sync wbs-sync-dry

# Mark nodes in progress / complete and regenerate docs/WBS.md in one step.
#   make start N="A3 A6"     make done N="A3-A6 B5"     make wbs-show N=B7
start:
	$(PYTHON) tools/wbs.py start $(N)

done:
	$(PYTHON) tools/wbs.py done $(N)

wbs-show:
	$(PYTHON) tools/wbs.py show $(N)

# Regenerate docs/WBS.md from the CSVs.
wbs:
	$(PYTHON) tools/wbs_render.py

# Regenerate docs/WBS.md and scaffold this week's docs/progress/<date>.md entry.
wbs-week:
	$(PYTHON) tools/wbs_render.py --new-entry

# Mirror milestones and node issues to GitHub (requires an authenticated gh CLI).
wbs-sync:
	$(PYTHON) tools/wbs_sync_github.py

# Show what wbs-sync would change on GitHub without changing anything.
wbs-sync-dry:
	$(PYTHON) tools/wbs_sync_github.py --dry-run
