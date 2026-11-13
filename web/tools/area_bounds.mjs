// C15, C17: the bounding box of every area, read from the delivered area tiles at build
// time, so the map can move to an area found by ZIP code or named in a link. B7 carries
// no bounds and no point for an area, and the browser can only read the tiles it has
// loaded, so the box is taken once here from every tile at one zoom level.
//
// A box is geometry, not a value about the area: it is not a metric (ICD 9, must not 1).
// It is built from the archive build.mjs has just checked against SHA256SUMS.

import { closeSync, openSync, readSync } from "node:fs";
import { VectorTile } from "@mapbox/vector-tile";
import { PbfReader } from "pbf";
import { PMTiles } from "pmtiles";

// At zoom 5 a tile spans about 11 degrees, so one tile unit is under 0.003 degrees; the
// whole archive is read in a fraction of a second.
const ZOOM = 5;
const PLACES = 1000;

// pmtiles reads through a Source; this one reads byte ranges from a local file.
function fileSource(path) {
  const fd = openSync(path, "r");
  return {
    source: {
      getKey: () => path,
      async getBytes(offset, length) {
        const buffer = Buffer.alloc(length);
        readSync(fd, buffer, 0, length, offset);
        return { data: buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + length) };
      },
    },
    close: () => closeSync(fd),
  };
}

function extend(box, coordinates) {
  if (typeof coordinates[0] === "number") {
    const [lng, lat] = coordinates;
    if (lng < box[0]) box[0] = lng;
    if (lat < box[1]) box[1] = lat;
    if (lng > box[2]) box[2] = lng;
    if (lat > box[3]) box[3] = lat;
  } else {
    for (const part of coordinates) extend(box, part);
  }
}

// Returns { code: [west, south, east, north] }, rounded outward to 0.001 degree.
export async function areaBounds(path, layerName = "areas") {
  const { source, close } = fileSource(path);
  try {
    const archive = new PMTiles(source);
    const header = await archive.getHeader();
    const zoom = Math.min(Math.max(ZOOM, header.minZoom), header.maxZoom);
    const boxes = {};
    const n = 2 ** zoom;
    for (let x = 0; x < n; x++) {
      for (let y = 0; y < n; y++) {
        const tile = await archive.getZxy(zoom, x, y);
        if (!tile) continue;
        const layer = new VectorTile(new PbfReader(new Uint8Array(tile.data))).layers[layerName];
        if (!layer) continue;
        for (let i = 0; i < layer.length; i++) {
          const feature = layer.feature(i);
          const code = String(feature.properties.code);
          boxes[code] ??= [Infinity, Infinity, -Infinity, -Infinity];
          extend(boxes[code], feature.toGeoJSON(x, y, zoom).geometry.coordinates);
        }
      }
    }
    const out = {};
    for (const code of Object.keys(boxes).sort()) {
      const [w, s, e, nth] = boxes[code];
      out[code] = [Math.floor(w * PLACES) / PLACES, Math.floor(s * PLACES) / PLACES, Math.ceil(e * PLACES) / PLACES, Math.ceil(nth * PLACES) / PLACES];
    }
    return out;
  } finally {
    close();
  }
}
