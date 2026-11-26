import type { TemplatePositionLimits } from "../../api/workspaceSettings";

export interface LimitDraft {
  smallestPercent: number;
  largestPercent: number;
  offsetPercent: number;
  tiltDegrees: number;
}

export const toDraft = (limits: TemplatePositionLimits): LimitDraft => ({
  smallestPercent: Math.round((limits.scale?.min ?? 0.8) * 100),
  largestPercent: Math.round((limits.scale?.max ?? 1.1) * 100),
  offsetPercent: Math.round(limits.offset * 100),
  tiltDegrees: Math.round(limits.rotation),
});

export const toLimits = (draft: LimitDraft): TemplatePositionLimits => ({
  scale: { min: draft.smallestPercent / 100, max: draft.largestPercent / 100 },
  offset: draft.offsetPercent / 100,
  rotation: draft.tiltDegrees,
});

/** The interactions table, *Settings: Template rendering*. */
export const ROWS: {
  key: keyof LimitDraft;
  label: string;
  hint: string;
  min: number;
  max: number;
  step: number;
  unit: string;
}[] = [
  {
    key: "smallestPercent",
    label: "Smallest",
    hint: "of the template's box",
    min: 50,
    max: 100,
    step: 5,
    unit: "%",
  },
  {
    key: "largestPercent",
    label: "Largest",
    hint: "of the template's box",
    min: 100,
    max: 150,
    step: 5,
    unit: "%",
  },
  {
    key: "offsetPercent",
    label: "Move",
    hint: "of box width or height, each way",
    min: 0,
    max: 25,
    step: 1,
    unit: "%",
  },
  { key: "tiltDegrees", label: "Tilt", hint: "each way", min: 0, max: 30, step: 1, unit: "°" },
];
