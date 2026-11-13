// C10: the legend. Classes, colours and labels come from the active scale in B21, plus the
// no-data colour with its meaning. The full list shows on wide screens and a compact ramp
// on phones.

function swatch(color) {
  const box = document.createElement("span");
  box.className = "legend-swatch";
  box.style.background = color;
  return box;
}

export function renderLegend(root, ui, scale) {
  root.replaceChildren();
  root.classList.remove("legend-clusters");

  const title = document.createElement("p");
  title.className = "legend-title";
  title.textContent = scale.label;
  const short = document.createElement("p");
  short.className = "legend-title-short";
  short.textContent = scale.shortLabel;
  root.append(title, short);

  if (scale.offStandard) {
    const note = document.createElement("p");
    note.className = "legend-scale";
    const { title: name, subtitle } = ui.grid.off_standard_scale;
    note.textContent = `${name}: ${subtitle}`;
    root.append(note);
  }

  const list = document.createElement("ul");
  list.className = "legend-list";
  scale.classLabels.forEach((label, index) => {
    const item = document.createElement("li");
    item.append(swatch(scale.colors[index]), document.createTextNode(label));
    list.append(item);
  });
  const none = document.createElement("li");
  none.append(swatch(ui.no_data_color), document.createTextNode(ui.no_data_label));
  list.append(none);

  const ramp = document.createElement("div");
  ramp.className = "legend-ramp";
  ramp.setAttribute("aria-hidden", "true");
  const bar = document.createElement("div");
  bar.className = "legend-bar";
  for (const color of scale.colors) bar.append(swatch(color));
  const ends = document.createElement("div");
  ends.className = "legend-ends";
  for (const text of scale.rampLabels) {
    const span = document.createElement("span");
    span.textContent = text;
    ends.append(span);
  }
  ramp.append(bar, ends);

  root.append(list, ramp);
}

// C16: the overlay's legend, in place of the metric legend while the overlay shows. Its
// title says the clusters are exploratory (ICD 9, must 5), and it names the FDR outline.
// The no-value item appears only when some area in the analysis has no value in this view.
export function renderClusterLegend(root, ui, { noValue }) {
  root.replaceChildren();
  root.classList.add("legend-clusters");
  const { clusters } = ui;

  const title = document.createElement("p");
  title.className = "legend-title legend-title-clusters";
  title.textContent = clusters.legend_title;
  root.append(title);

  const list = document.createElement("ul");
  list.className = "legend-list";
  const item = (box, text, id) => {
    const li = document.createElement("li");
    if (id) li.dataset.cluster = id;
    li.append(box, document.createTextNode(text));
    list.append(li);
  };
  for (const [id, { label, color }] of Object.entries(clusters.classes)) item(swatch(color), label, id);

  const outline = swatch("transparent");
  outline.classList.add("legend-swatch-outline");
  outline.style.border = `${clusters.fdr_marker.outline_width}px solid ${clusters.fdr_marker.outline_color}`;
  item(outline, clusters.fdr_marker.label, "fdr");

  if (noValue) item(swatch(ui.no_data_color), ui.no_data_label, "no_value");

  const empty = swatch("transparent");
  empty.classList.add("legend-swatch-empty");
  item(empty, clusters.out_of_scope_label, "out_of_scope");

  root.append(list);
}
