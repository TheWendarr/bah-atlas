// C25: the authorized-standard notice, filled from B21. Every view carries one (ICD 9,
// must 8). Pure: returns text.

const labelOf = (list, id) => list.find((item) => item.id === id)?.label ?? id;

export function noticeText(ui, state, standardView) {
  const standard = ui.grid.standards_text[state.rank][state.dependents];
  const template = standardView ? ui.grid.notice.standard : ui.grid.notice.off_standard;
  const homeType = labelOf(ui.grid.home_types, state.homeType);
  return template.replaceAll("{standard}", standard).replaceAll("{home_type}", homeType);
}

export { labelOf };
