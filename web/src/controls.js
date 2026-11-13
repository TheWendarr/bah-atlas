// C7, C13: the selection controls. Native <select> and radio inputs, so keyboard,
// screen-reader and phone behaviour come from the browser. Option labels come from B21;
// only the wording that describes no data lives here (ICD 9, D29).

import { labelOf } from "./notice.js";

const UI = {
  edit: "Change",
  done: "Done",
  overlay: "Show local clusters",
  // Names the views the overlay exists for, from B21's profile and home-type labels.
  overlayOnly: (profiles, standard) => `Only for ${profiles.join(" and ")} at the ${standard}`,
};

function select(id, title, options) {
  const wrap = document.createElement("label");
  wrap.className = "control";
  wrap.htmlFor = id;
  const caption = document.createElement("span");
  caption.className = "control-title";
  caption.textContent = title;
  const input = document.createElement("select");
  input.id = id;
  for (const { id: value, label } of options) input.add(new Option(label, value));
  wrap.append(caption, input);
  return { wrap, input };
}

function modeGroup(title, modes) {
  const set = document.createElement("fieldset");
  set.className = "control control-mode";
  const legend = document.createElement("legend");
  legend.className = "control-title";
  legend.textContent = title;
  set.append(legend);
  const inputs = modes.map(({ id, label }) => {
    const option = document.createElement("label");
    option.className = "mode-option";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "mode";
    input.value = id;
    const text = document.createElement("span");
    text.textContent = label;
    option.append(input, text);
    set.append(option);
    return input;
  });
  return { wrap: set, inputs };
}

// C16: the overlay switch. It is a checkbox, not a select: it adds a layer rather than
// choosing a value. Off a research view it is disabled and says which views have one.
function overlaySwitch(ui) {
  const wrap = document.createElement("div");
  wrap.className = "control control-overlay";
  const label = document.createElement("label");
  label.className = "overlay-option";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.id = "overlay";
  input.setAttribute("aria-describedby", "overlay-hint");
  const text = document.createElement("span");
  text.textContent = UI.overlay;
  label.append(input, text);
  const hint = document.createElement("span");
  hint.id = "overlay-hint";
  hint.className = "overlay-hint";
  const standard = ui.grid.home_types.find((type) => type.id === "standard").label;
  hint.textContent = UI.overlayOnly(ui.profiles.map((profile) => profile.label), standard);
  wrap.append(label, hint);
  return { wrap, input, hint };
}

export function createControls(root, ui, store) {
  const titles = ui.grid.titles;
  const rank = select("rank", titles.rank, ui.grid.ranks);
  const dependents = select("dependents", titles.dependents, ui.grid.dependents);
  const homeType = select("home-type", titles.home_type, ui.grid.home_types);
  const metric = select("metric", titles.metric, ui.grid.metrics.map((id) => ({ id, label: ui.metrics[id].short_label })));
  const mode = modeGroup(titles.mode, ui.modes);
  const overlay = overlaySwitch(ui);

  // Layout C on phones: a summary chip opens the controls as a sheet.
  const chip = document.createElement("button");
  chip.type = "button";
  chip.className = "controls-chip";
  chip.setAttribute("aria-expanded", "false");
  chip.setAttribute("aria-controls", "controls-fields");
  const chipText = document.createElement("span");
  const chipAction = document.createElement("span");
  chipAction.className = "controls-chip-action";
  chip.append(chipText, chipAction);

  const fields = document.createElement("div");
  fields.id = "controls-fields";
  fields.className = "controls-fields";
  fields.append(rank.wrap, dependents.wrap, homeType.wrap, mode.wrap, metric.wrap, overlay.wrap);
  root.append(chip, fields);

  const setOpen = (open) => {
    root.classList.toggle("open", open);
    chip.setAttribute("aria-expanded", String(open));
    chipAction.textContent = open ? UI.done : UI.edit;
  };
  chip.addEventListener("click", () => setOpen(!root.classList.contains("open")));
  setOpen(false);

  rank.input.addEventListener("change", () => store.set({ rank: rank.input.value }));
  dependents.input.addEventListener("change", () => store.set({ dependents: dependents.input.value }));
  homeType.input.addEventListener("change", () => store.set({ homeType: homeType.input.value }));
  metric.input.addEventListener("change", () => store.set({ metric: metric.input.value }));
  for (const input of mode.inputs) input.addEventListener("change", () => store.set({ mode: input.value }));
  overlay.input.addEventListener("change", () => store.set({ overlay: overlay.input.checked }));

  // Called by render with the current state, whether it is the statutory view, and the
  // research profile it is the statutory view of (null for any other view).
  return function update(state, standardView, research = null) {
    rank.input.value = state.rank;
    dependents.input.value = state.dependents;
    homeType.input.value = state.homeType;
    for (const input of mode.inputs) input.checked = input.value === state.mode;
    // Metric names follow the active scale (D27), so an off-standard view never borrows
    // the statutory wording.
    for (const option of metric.input.options) {
      const def = ui.metrics[option.value];
      option.textContent = !standardView && def.off_standard ? def.off_standard.short_label : def.short_label;
      option.disabled = !def.modes.includes(state.mode);
    }
    metric.input.value = state.metric;
    overlay.input.disabled = research === null;
    overlay.input.checked = state.overlay && research !== null;
    overlay.hint.hidden = research !== null;
    chipText.textContent = [
      labelOf(ui.grid.ranks, state.rank),
      labelOf(ui.grid.dependents, state.dependents),
      labelOf(ui.grid.home_types, state.homeType),
      labelOf(ui.modes, state.mode),
    ].join(" · ");
  };
}
