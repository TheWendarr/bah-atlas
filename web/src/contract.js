// C5: load the delivered files and enforce ICD section 9, obligation 6. If they do not
// share one build and a known major version, the map must refuse to render.

const SUPPORTED_MAJOR = 1;

const fileNames = (year) => ({
  payload: `payload_${year}.json`,
  ui: `ui_metadata_${year}.json`,
  hotspots: `hotspots_${year}.json`,
  grid: `grid_${year}.json`,
});

// C20: B22 has no build_id of its own. Its SHA-256 is the build id the other files carry
// (ICD section 8), so the page checks that hash before it shows B22's date and commit.
const manifestName = (year) => `build_manifest_${year}.json`;

async function fetchOk(url, name) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
  return response;
}

export async function sha256Hex(buffer) {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function loadFiles(dataPath, year) {
  // All five requests start together: on a slow connection each round trip counts (X9).
  const name = manifestName(year);
  const [entries, bytes] = await Promise.all([
    Promise.all(
      Object.entries(fileNames(year)).map(async ([key, file]) => {
        const response = await fetchOk(`${dataPath}/${file}`, file);
        return [key, await response.json()];
      }),
    ),
    fetchOk(`${dataPath}/${name}`, name).then((response) => response.arrayBuffer()),
  ]);
  const manifest = {
    name,
    sha256: await sha256Hex(bytes),
    content: JSON.parse(new TextDecoder().decode(bytes)),
  };
  return { files: Object.fromEntries(entries), manifest };
}

export function checkContract(files) {
  const problems = [];
  const names = Object.keys(files);
  for (const name of names) {
    const major = Number(String(files[name].schema_version).split(".")[0]);
    if (major !== SUPPORTED_MAJOR) {
      problems.push(`${name}: schema_version ${files[name].schema_version}, this map reads major version ${SUPPORTED_MAJOR}`);
    }
  }
  const ids = new Set(names.map((name) => files[name].build_id));
  if (ids.size !== 1) {
    problems.push(`Expected one build id. Found ${[...ids].map((id) => String(id).slice(0, 8)).join(" and ")}.`);
  }
  return problems;
}

// The build manifest must be the one the other files name, and of a major version the map reads.
export function checkManifest(manifest, buildId) {
  const problems = [];
  const major = Number(String(manifest.content.schema_version).split(".")[0]);
  if (major !== SUPPORTED_MAJOR) {
    problems.push(`${manifest.name}: schema_version ${manifest.content.schema_version}, this map reads major version ${SUPPORTED_MAJOR}`);
  }
  if (manifest.sha256 !== buildId) {
    problems.push(`${manifest.name}: its SHA-256 begins ${manifest.sha256.slice(0, 8)}, but the build id begins ${String(buildId).slice(0, 8)}.`);
  }
  return problems;
}
