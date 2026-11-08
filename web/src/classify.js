// C9: the ICD section 6 class rule. A value belongs to class i, where i is the number of
// breaks less than or equal to it, so a value equal to a break falls in the class above.
// The map classifies rounded values (ICD section 6, rounding at breaks).

export const NO_CLASS = -1;

export function classIndex(value, breaks) {
  if (value === null) return NO_CLASS;
  return breaks.filter((limit) => limit <= value).length;
}

// D27: a view that is not the statutory test reads on the metric's wider off-standard
// scale, with its own labels. Both scales share the metric's colours.
export function scaleFor(metric, standardView) {
  const source = !standardView && metric.off_standard ? metric.off_standard : metric;
  return {
    offStandard: source !== metric,
    label: source.label,
    shortLabel: source.short_label,
    breaks: source.breaks,
    classLabels: source.class_labels,
    rampLabels: source.ramp_labels,
    colors: metric.colors,
    format: metric.format,
    neutral: source.neutral,
  };
}
