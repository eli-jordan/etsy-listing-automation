import type { MaskEdit, MaskHistory } from "../api/preparation";
import type { maskDraft } from "../components/maskDraft";
import type { PreviewJob } from "../components/PreviewPanel";
import type { Placement, TemplateConfigState } from "../types";

/** The id of the one placement a single-box template is drawn as. */
export const IMPLICIT_PLACEMENT_ID = "implicit";

export function pickOrFirst(selected: string | null, options: readonly string[]): string {
  return selected !== null && options.includes(selected) ? selected : (options[0] ?? "");
}

export function editorPlacements(config: TemplateConfigState, colours: string[]): Placement[] {
  if (config.kind === "multiple") return config.placements;
  const colour = config.kind === "single" ? (config.colour ?? "") : (colours[0] ?? "");
  return [{ id: IMPLICIT_PLACEMENT_ID, colour, bounding_box: config.bounding_box }];
}

export function previewJobs(
  config: TemplateConfigState,
  colours: string[],
  templateName: string,
): PreviewJob[] {
  if (config.kind === "colour-matrix") {
    return colours.map((c) => ({
      id: c,
      label: c,
      body: { colour: c, bounding_box: config.bounding_box, renderer: config.renderer },
    }));
  }
  const body =
    config.kind === "multiple"
      ? { placements: config.placements, renderer: config.renderer }
      : { bounding_box: config.bounding_box, renderer: config.renderer };
  return [{ id: templateName, label: templateName, body }];
}

export function editorPreviewRequest(
  kind: TemplateConfigState["kind"],
  jobs: PreviewJob[],
  colour: string,
  revision: string,
  labels: string[],
  maskEdits: MaskEdit[],
) {
  if (!revision) return null;
  const body =
    kind === "colour-matrix" ? jobs.find((job) => job.id === colour)?.body : jobs[0]?.body;
  if (!body) return null;
  return { ...body, calibration_revision: revision, labels, mask_edits: maskEdits };
}

export function marigoldMapInputs(value: TemplateConfigState | null): string | null {
  if (value?.renderer.type !== "marigold") return null;
  return JSON.stringify({
    kind: value.kind,
    geometry:
      value.kind === "multiple"
        ? value.placements.map((p) => ({ id: p.id, bounding_box: p.bounding_box }))
        : value.bounding_box,
    inference: value.renderer.config.inference,
  });
}

export function undoBases(
  histories: { revision: string; values: Record<string, MaskHistory> },
  revision: string,
  id: string | null,
): string[] {
  if (histories.revision !== revision) return [];
  return histories.values[id ?? IMPLICIT_PLACEMENT_ID]?.strokes.map((s) => s.before) ?? [];
}

export function canUndoMask(draft: ReturnType<typeof maskDraft>, undoCount: number): boolean {
  if (draft.strokes.length > 0) return true;
  return !draft.automatic && undoCount > draft.undoSaved;
}

export function previewBlocker(facts: {
  mapsReady: boolean;
  unsavedMaps: boolean;
  awaitingSavedRevision: boolean;
  activeJob: boolean;
  mapsMessage: string | null | undefined;
}): string | null {
  const { mapsReady, unsavedMaps, awaitingSavedRevision, activeJob } = facts;
  if (mapsReady && !unsavedMaps && !awaitingSavedRevision && !activeJob) return null;
  if (unsavedMaps) return "Save your calibration changes before rendering.";
  if (awaitingSavedRevision) {
    return "Waiting for current calibration status. Reload the template if it changed elsewhere.";
  }
  return facts.mapsMessage ?? "Prepare the template first.";
}
