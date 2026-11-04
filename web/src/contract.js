// C5: load the delivered files and enforce ICD section 9, obligation 6. If they do not
// share one build and a known major version, the map must refuse to render.

const SUPPORTED_MAJOR = 1;

const fileNames = (year) => ({
  payload: `payload_${year}.json`,
  ui: `ui_metadata_${year}.json`,
  hotspots: `hotspots_${year}.json`,
  grid: `grid_${year}.json`,
});

export async function loadFiles(dataPath, year) {
  const entries = await Promise.all(
    Object.entries(fileNames(year)).map(async ([key, name]) => {
      const response = await fetch(`${dataPath}/${name}`);
      if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
      return [key, await response.json()];
    }),
  );
  return Object.fromEntries(entries);
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
