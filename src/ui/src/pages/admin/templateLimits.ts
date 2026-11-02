import type { TemplatePositionLimits } from "../../api/workspaceSettings";

/** The sliders' whole-number view of the limits: percentages and degrees. */
export interface LimitDraft {
  smallest: number;
  largest: number;
  offset: number;
  tilt: number;
}

export const toDraft = (limits: TemplatePositionLimits): LimitDraft => ({
  smallest: Math.round((limits.scale?.min ?? 0.8) * 100),
  largest: Math.round((limits.scale?.max ?? 1.1) * 100),
  offset: Math.round(limits.offset * 100),
  tilt: Math.round(limits.rotation),
});

export const toLimits = (draft: LimitDraft): TemplatePositionLimits => ({
  scale: { min: draft.smallest / 100, max: draft.largest / 100 },
  offset: draft.offset / 100,
  rotation: draft.tilt,
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
    key: "smallest",
    label: "Smallest",
    hint: "of the template's box",
    min: 50,
    max: 100,
    step: 5,
    unit: "%",
  },
  {
    key: "largest",
    label: "Largest",
    hint: "of the template's box",
    min: 100,
    max: 150,
    step: 5,
    unit: "%",
  },
  {
    key: "offset",
    label: "Move",
    hint: "of box width or height, each way",
    min: 0,
    max: 25,
    step: 1,
    unit: "%",
  },
  { key: "tilt", label: "Tilt", hint: "each way", min: 0, max: 30, step: 1, unit: "°" },
];
