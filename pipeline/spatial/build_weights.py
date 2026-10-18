#!/usr/bin/env python3
"""
build_weights.py  (2.6 spatial statistics: B16 spatial weights matrix)

  B16  spatial weights for the MHA polygons    B6

    python pipeline/spatial/build_weights.py \
        --geometry data/processed/mha_2026.gpkg \
        --out data/interim/spatial_2026 --k 6

------------------------------------------------------------------------------
Why k-nearest neighbours, not contiguity
------------------------------------------------------------------------------
MHA polygons are dissolves of the ZCTAs DTMO assigns to each MHA (B6). The
counties between MHAs belong to County Cost Groups, which are a separate
geography and are not in B6, so many MHAs touch no other MHA. Under queen or
rook contiguity those MHAs are islands: they have no neighbours, drop out of
every local statistic, and leave the global test running on a broken graph.
k-nearest neighbours gives every MHA exactly k neighbours whatever the gaps
between them, so every MHA is tested and every local statistic uses the same
number of neighbours.

Queen contiguity is still built, as a diagnostic: the manifest records how many
MHAs it would leave as islands and how many disconnected pieces it splits the
map into. That count is the evidence for the choice above. Queen weights are
also used as a sensitivity check on the global test in B17.

------------------------------------------------------------------------------
Method
------------------------------------------------------------------------------
  scope     CONUS only (research proposal: "CONUS-first"). MHAs coded AK, HI or
            a territory prefix are excluded and listed; their nearest
            neighbours would be thousands of kilometres away across water.
  CRS       EPSG:5070 (NAD83 / Conus Albers, equal area), so distances are in
            metres on a projection built for the lower 48.
  points    one representative point per MHA (guaranteed to fall inside the
            polygon; a centroid of a multipart or crescent-shaped MHA can land
            outside it).
  KNN       for each MHA, the k other MHAs whose points are closest. Ties in
            distance break on MHA code so the result is reproducible. KNN is
            not symmetric (A can be among B's nearest without B among A's);
            the share of one-way links is reported.
  queen     polygons sharing at least one boundary vertex.

The neighbour lists are stored unweighted. Each statistic applies its own
transform: row-standardized for Moran's I and LISA, binary for Getis-Ord Gi*.

------------------------------------------------------------------------------
Output (written to --out)
------------------------------------------------------------------------------
  mha_weights_knn<k>.gal     neighbour lists in GAL format (GeoDa / PySAL)
  mha_neighbors.csv          one row per KNN link: mha, neighbor, rank,
                             distance_km, queen (whether the pair also touches)
  mha_weights_summary.csv    one row per B6 MHA: scope, representative point,
                             queen neighbour count, KNN distances, component
  weights_manifest.json      input hash, scope, CRS, k, and diagnostics for
                             both weight sets

The functions here are also imported by spatial_stats.py (B17, B18), which
rebuilds the KNN weights on the MHAs that have a value for each test.

------------------------------------------------------------------------------
Validation (loud)
------------------------------------------------------------------------------
  * B6 has an `mha` column of unique real MHA codes and no empty geometries
  * k is at least 1 and smaller than the number of in-scope MHAs
  * warns (does not stop) when queen contiguity leaves islands, and when a
    KNN link is longer than 500 km
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "benchmarks"))
import mha_agg as agg  # noqa: E402

TOOL = "build_weights"
MHA_CODE = re.compile(r"^[A-Z]{2}\d{3}$")
ANALYSIS_CRS = "EPSG:5070"
# MHA codes start with the state or territory. Everything outside the lower 48 + DC is out of scope.
OUT_OF_SCOPE_PREFIXES = ("AK", "HI", "PR", "GU", "VI", "AS", "MP")
LONG_LINK_KM = 500.0

try:
    import geopandas as gpd
    import numpy as np
    from libpysal.weights import W, Queen
except ImportError as e:  # pragma: no cover - environment problem, reported loudly
    sys.exit(f"{TOOL}: {e.name} is not installed. Run `pip install -r requirements.txt`.")


# --- geometry -----------------------------------------------------------------

def load_geometry(path: Path, tool: str = TOOL) -> "gpd.GeoDataFrame":
    """B6 polygons, one row per MHA, sorted by code, in the analysis CRS."""
    if not path.exists():
        agg.die(tool, f"B6 geometry not found: {path} (run `make geometry` first)")
    g = gpd.read_file(path)
    problems: list[str] = []
    if "mha" not in g.columns:
        agg.die(tool, f"{path.name} needs an 'mha' column; found {list(g.columns)}")
    if g.crs is None:
        agg.die(tool, f"{path.name} has no CRS; B6 is written in EPSG:4326")
    g["mha"] = g["mha"].astype(str).str.strip().str.upper()
    bad = sorted(m for m in g["mha"] if not MHA_CODE.match(m))
    if bad:
        problems.append(f"{len(bad)} code(s) are not real MHA codes: {', '.join(bad[:10])}")
    dupes = sorted(g.loc[g["mha"].duplicated(), "mha"].unique())
    if dupes:
        problems.append(f"{len(dupes)} MHA code(s) appear more than once: {', '.join(dupes[:10])}")
    empty = sorted(g.loc[g.geometry.isna() | g.geometry.is_empty, "mha"])
    if empty:
        problems.append(f"{len(empty)} MHA(s) have no geometry: {', '.join(empty[:10])}")
    agg.fail_if([f"B6 {path.name}: {p}" for p in problems], tool)
    g = g[["mha", "geometry"]].to_crs(ANALYSIS_CRS)
    return g.sort_values("mha").reset_index(drop=True)


def in_scope(code: str) -> bool:
    return not code.startswith(OUT_OF_SCOPE_PREFIXES)


def split_scope(g: "gpd.GeoDataFrame") -> tuple["gpd.GeoDataFrame", list[str]]:
    keep = g["mha"].map(in_scope)
    return g[keep].reset_index(drop=True), sorted(g.loc[~keep, "mha"])


def points(g: "gpd.GeoDataFrame") -> "np.ndarray":
    """(n, 2) representative points in metres, in the row order of g."""
    rp = g.geometry.representative_point()
    return np.column_stack([rp.x.to_numpy(), rp.y.to_numpy()])


# --- weights ------------------------------------------------------------------

def knn_weights(ids: list[str], xy: "np.ndarray", k: int, tool: str = TOOL) -> tuple["W", dict]:
    """k nearest neighbours, ties broken on code. Returns the W and {(i, j): metres}."""
    n = len(ids)
    if k < 1 or k >= n:
        agg.die(tool, f"k = {k} needs between 1 and {n - 1} (there are {n} MHAs to link)")
    d = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(axis=2))
    neighbors: dict[str, list[str]] = {}
    dist: dict[tuple[str, str], float] = {}
    for i, a in enumerate(ids):
        order = sorted((j for j in range(n) if j != i), key=lambda j: (d[i, j], ids[j]))[:k]
        neighbors[a] = [ids[j] for j in order]
        for j in order:
            dist[(a, ids[j])] = float(d[i, j])
    return W(neighbors, id_order=list(ids), silence_warnings=True), dist


def queen_weights(g: "gpd.GeoDataFrame") -> "W":
    return Queen.from_dataframe(g, ids=g["mha"].tolist(), use_index=False, silence_warnings=True)


def components(w: "W") -> tuple[int, dict[str, int]]:
    """Connected pieces of the graph (links read both ways), labelled by size, largest first."""
    adj: dict[str, set[str]] = {i: set() for i in w.id_order}
    for i, ns in w.neighbors.items():
        for j in ns:
            adj[i].add(j)
            adj[j].add(i)
    seen: dict[str, int] = {}
    pieces: list[list[str]] = []
    for start in w.id_order:
        if start in seen:
            continue
        stack, piece = [start], []
        seen[start] = -1
        while stack:
            v = stack.pop()
            piece.append(v)
            for u in adj[v]:
                if u not in seen:
                    seen[u] = -1
                    stack.append(u)
        pieces.append(piece)
    pieces.sort(key=lambda p: (-len(p), min(p)))
    label = {v: n for n, piece in enumerate(pieces) for v in piece}
    return len(pieces), label


def asymmetric_share(w: "W") -> float:
    links = [(i, j) for i, ns in w.neighbors.items() for j in ns]
    if not links:
        return 0.0
    one_way = sum(1 for i, j in links if i not in w.neighbors.get(j, []))
    return one_way / len(links)


def write_gal(path: Path, w: "W") -> None:
    """GAL text: header '0 n', then 'id count' and the neighbour ids for each unit."""
    lines = [f"0 {w.n}"]
    for i in w.id_order:
        ns = w.neighbors[i]
        lines.append(f"{i} {len(ns)}")
        lines.append(" ".join(ns))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- main -----------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geometry", type=Path, required=True, help="B6 mha_YYYY.gpkg (or .geojson)")
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    ap.add_argument("--k", type=int, default=6, help="neighbours per MHA (default 6)")
    args = ap.parse_args()

    g_all = load_geometry(args.geometry)
    g, excluded = split_scope(g_all)
    ids = g["mha"].tolist()
    print(f"B16 spatial weights: {len(g_all)} MHAs in B6, {len(ids)} in scope (CONUS), "
          f"{len(excluded)} excluded ({', '.join(excluded) or 'none'})")

    xy = points(g)
    knn, dist = knn_weights(ids, xy, args.k)
    queen = queen_weights(g)
    knn_pieces, knn_label = components(knn)
    queen_pieces, _ = components(queen)
    queen_islands = sorted(queen.islands)
    warnings: list[str] = []

    km = {pair: m / 1000 for pair, m in dist.items()}
    long_links = sorted((round(v, 1), a, b) for (a, b), v in km.items() if v > LONG_LINK_KM)
    if long_links:
        warnings.append(f"{len(long_links)} KNN link(s) longer than {LONG_LINK_KM:.0f} km; longest "
                        f"{long_links[-1][1]}->{long_links[-1][2]} {long_links[-1][0]} km")
    if queen_islands:
        warnings.append(f"queen contiguity leaves {len(queen_islands)} of {len(ids)} MHAs with no neighbour "
                        f"and splits the map into {queen_pieces} pieces; KNN is the primary weights")

    # --- write ---
    gal = f"mha_weights_knn{args.k}.gal"
    write_gal(args.out / gal, knn)
    link_rows = []
    for a in ids:
        for rank, b in enumerate(knn.neighbors[a], start=1):
            link_rows.append({"mha": a, "neighbor": b, "rank": rank, "distance_km": f"{km[(a, b)]:.1f}",
                              "queen": str(b in queen.neighbors.get(a, [])).lower()})
    agg.write_csv(args.out / "mha_neighbors.csv", ["mha", "neighbor", "rank", "distance_km", "queen"], link_rows)

    pos = {m: i for i, m in enumerate(ids)}
    summary_rows = []
    for m in g_all["mha"]:
        if m not in pos:
            summary_rows.append({"mha": m, "in_scope": "false"})
            continue
        i = pos[m]
        ds = [km[(m, b)] for b in knn.neighbors[m]]
        summary_rows.append({
            "mha": m, "in_scope": "true", "x_m": f"{xy[i, 0]:.0f}", "y_m": f"{xy[i, 1]:.0f}",
            "queen_neighbors": len(queen.neighbors.get(m, [])),
            "knn_nearest_km": f"{min(ds):.1f}", "knn_farthest_km": f"{max(ds):.1f}",
            "knn_component": knn_label[m]})
    agg.write_csv(args.out / "mha_weights_summary.csv",
                  ["mha", "in_scope", "x_m", "y_m", "queen_neighbors", "knn_nearest_km", "knn_farthest_km",
                   "knn_component"], summary_rows)

    farthest = [max(km[(m, b)] for b in knn.neighbors[m]) for m in ids]
    queen_counts = [len(queen.neighbors.get(m, [])) for m in ids]
    manifest = {
        "node": "B16",
        "generated_at": agg.now_utc(),
        "inputs": {"B6": args.geometry.name},
        "input_sha256": {"B6": agg.sha256(args.geometry)},
        "scope": {
            "rule": "CONUS only: MHA codes starting " + ", ".join(OUT_OF_SCOPE_PREFIXES) + " are excluded",
            "mhas_in_b6": len(g_all),
            "mhas_in_scope": len(ids),
            "excluded": excluded,
            "excluded_prefixes": list(OUT_OF_SCOPE_PREFIXES),
        },
        "crs": ANALYSIS_CRS,
        "points": "representative point of each MHA polygon (always inside the polygon)",
        "primary": {
            "scheme": "knn",
            "k": args.k,
            "tie_break": "distance, then MHA code",
            "transform_note": "stored unweighted; row-standardized for Moran's I and LISA, binary for Gi*",
            "file": gal,
            "components": knn_pieces,
            "asymmetric_link_share": round(asymmetric_share(knn), 4),
            "nearest_neighbor_km": {"min": round(min(km.values()), 1),
                                    "median": round(statistics.median(
                                        km[(m, knn.neighbors[m][0])] for m in ids), 1)},
            "kth_neighbor_km": {"min": round(min(farthest), 1),
                                "median": round(statistics.median(farthest), 1),
                                "max": round(max(farthest), 1)},
            "links_over_500_km": len(long_links),
        },
        "diagnostic_queen": {
            "scheme": "queen contiguity (shared vertex)",
            "islands": len(queen_islands),
            "island_mhas": queen_islands,
            "components": queen_pieces,
            "mean_neighbors": round(statistics.mean(queen_counts), 2),
            "neighbor_count_distribution": {str(c): queen_counts.count(c) for c in sorted(set(queen_counts))},
            "knn_links_that_also_touch": sum(r["queen"] == "true" for r in link_rows),
            "knn_links": len(link_rows),
        },
        "outputs": [gal, "mha_neighbors.csv", "mha_weights_summary.csv", "weights_manifest.json"],
        "warnings": warnings,
    }
    agg.write_manifest(args.out / "weights_manifest.json", manifest)

    print(f"  KNN k={args.k}: {len(link_rows)} links, {knn_pieces} component(s), "
          f"k-th neighbour median {manifest['primary']['kth_neighbor_km']['median']} km, "
          f"max {manifest['primary']['kth_neighbor_km']['max']} km")
    print(f"  queen (diagnostic): {len(queen_islands)} island(s), {queen_pieces} component(s), "
          f"mean {manifest['diagnostic_queen']['mean_neighbors']} neighbours")
    for w_ in warnings:
        print(f"  WARNING: {w_}")
    print(f"  wrote {args.out}/{gal}, mha_neighbors.csv, mha_weights_summary.csv, weights_manifest.json")


if __name__ == "__main__":
    main()
