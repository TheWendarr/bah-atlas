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
