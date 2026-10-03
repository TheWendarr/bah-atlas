# BAH Atlas pipeline. Adjust YEAR and the ZCTA file as releases change.
YEAR ?= 2026
BAH_ZIP  ?= data/raw/BAH-ASCII-$(YEAR).zip
ZCTA_SHP ?= data/raw/cb_2020_us_zcta520_500k.shp
INTERIM  ?= data/interim/bah_$(YEAR)
PROCESSED?= data/processed

.PHONY: all ingest geometry clean

all: geometry

# Stage 1: translate the DTMO BAH ASCII release into tidy CSVs + manifest.
ingest: $(BAH_ZIP)
	python pipeline/ingest/ingest_bah_ascii.py --zip $(BAH_ZIP) --out $(INTERIM)

# Stage 2: dissolve ZCTA polygons up to MHA level using the ingested crosswalk.
geometry: ingest
	python pipeline/geometry/build_mha_geometry.py \
		--crosswalk $(INTERIM)/zip_mha_geo.csv \
		--zcta $(ZCTA_SHP) \
		--out $(PROCESSED)/mha_$(YEAR).gpkg

clean:
	rm -rf $(INTERIM) $(PROCESSED)/mha_$(YEAR).gpkg $(PROCESSED)/mha_$(YEAR).geojson

# --- Project tracking (living WBS) -------------------------------------------
# Source of truth: docs/wbs/nodes.csv and docs/wbs/milestones.csv.
.PHONY: wbs wbs-week wbs-sync wbs-sync-dry

# Regenerate docs/WBS.md from the CSVs.
wbs:
	python tools/wbs_render.py

# Regenerate docs/WBS.md and scaffold this week's docs/progress/<date>.md entry.
wbs-week:
	python tools/wbs_render.py --new-entry

# Mirror milestones and node issues to GitHub (requires an authenticated gh CLI).
wbs-sync:
	python tools/wbs_sync_github.py

# Show what wbs-sync would change on GitHub without changing anything.
wbs-sync-dry:
	python tools/wbs_sync_github.py --dry-run
