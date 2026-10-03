#!/usr/bin/env bash
# build_basemap.sh  (A11 -> served basemap, C4)
#
# Cut a self-hosted basemap out of a Protomaps daily planet build. Only the tiles
# inside the bounding box are downloaded (HTTP range requests), never the full
# ~120 GB planet. Output: data/processed/basemap.pmtiles + a provenance JSON.
#
# Requires the pmtiles CLI: https://github.com/protomaps/go-pmtiles/releases
#   (download the Linux_x86_64 tarball, put `pmtiles` on your PATH)
#
# Settings (environment variables):
#   BBOX     min_lon,min_lat,max_lon,max_lat   default: CONUS
#   MAXZOOM  highest zoom kept                 default: 10 (try 6 for a quick test)
#   DATE     build date YYYYMMDD               default: newest build in the last 8 days
#   OUT      output path                       default: data/processed/basemap.pmtiles
#
# Examples:
#   make basemap
#   MAXZOOM=6 make basemap                          # small, fast trial run
#   BBOX=-180,18,-154,72 OUT=data/processed/basemap_ak_hi.pmtiles make basemap
#
# Licence: the basemap is an ODbL Produced Work; credit "© OpenStreetMap contributors"
# and Protomaps on the map (C20 attribution node).
set -euo pipefail

PMTILES="${PMTILES:-pmtiles}"
BBOX="${BBOX:--125.0,24.4,-66.9,49.4}"
MAXZOOM="${MAXZOOM:-10}"
OUT="${OUT:-data/processed/basemap.pmtiles}"
BASE_URL="${BASE_URL:-https://build.protomaps.com}"

die() { echo "build_basemap: $*" >&2; exit 1; }

command -v "$PMTILES" >/dev/null 2>&1 || die "pmtiles CLI not found. Download it from \
https://github.com/protomaps/go-pmtiles/releases (Linux_x86_64), unpack, and put it on your PATH."

if [[ -z "${DATE:-}" ]]; then
  # Daily builds are kept for about a week; take the newest that answers.
  for back in 0 1 2 3 4 5 6 7 8; do
    candidate="$(date -u -d "-${back} day" +%Y%m%d)"
    # 1-byte range GET: works even where HEAD requests are refused.
    if curl -sf -r 0-0 -o /dev/null "${BASE_URL}/${candidate}.pmtiles" 2>/dev/null; then
      DATE="$candidate"; break
    fi
  done
  [[ -n "${DATE:-}" ]] || die "no Protomaps build found in the last 8 days at ${BASE_URL}; set DATE=YYYYMMDD"
fi
URL="${BASE_URL}/${DATE}.pmtiles"

mkdir -p "$(dirname "$OUT")"
TMP="${OUT%.pmtiles}.tmp.pmtiles"
rm -f "$TMP"

echo "A11 basemap: extracting ${URL}"
echo "  bbox ${BBOX}   maxzoom ${MAXZOOM}   ->  ${OUT}"
"$PMTILES" extract "$URL" "$TMP" --bbox="$BBOX" --maxzoom="$MAXZOOM"

[[ -s "$TMP" ]] || die "extract produced no output"
[[ "$(head -c 7 "$TMP")" == "PMTiles" ]] || { rm -f "$TMP"; die "output is not a PMTiles archive"; }
mv -f "$TMP" "$OUT"

SHA="$(sha256sum "$OUT" | cut -d' ' -f1)"
BYTES="$(stat -c %s "$OUT")"
cat > "${OUT%.pmtiles}_provenance.json" <<EOF
{
  "node": "A11",
  "served_as": "C4",
  "source": "Protomaps basemap daily build (OpenStreetMap-derived)",
  "source_url": "${URL}",
  "build_date": "${DATE}",
  "bbox": "${BBOX}",
  "maxzoom": ${MAXZOOM},
  "output_file": "$(basename "$OUT")",
  "output_sha256": "${SHA}",
  "output_bytes": ${BYTES},
  "license": "ODbL Produced Work; attribution: (c) OpenStreetMap contributors, Protomaps",
  "generated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
echo "A11 basemap: $(numfmt --to=iec "$BYTES") written, sha256 ${SHA:0:12}…"
