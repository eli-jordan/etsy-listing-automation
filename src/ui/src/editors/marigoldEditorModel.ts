import type { MaskEdit, MaskHistory } from "../api/preparation";
import type { maskDraft } from "../components/maskDraft";
import type { PreviewJob } from "../components/PreviewPanel";
import type { Placement, TemplateConfigState } from "../types";

/** The boxes the Marigold editor draws: a multiple template's own
 * placements, or one implicit placement for a single box. */
export function editorPlacements(config: TemplateConfigState, colours: string[]): Placement[] {
  if (config.kind === "multiple") return config.placements;
  const colour = config.kind === "single" ? (config.colour ?? "") : (colours[0] ?? "");
  return [{ id: "implicit", colour, bounding_box: config.bounding_box }];
}

/** What the preview tab renders: one image per colour for a colour matrix,
 * else one image of the whole template. */
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

/** The editor canvas's own preview: the job for the chosen colour (the only
 * job, for other kinds) at the calibration revision and that revision's
 * labels, with the unsaved mask strokes. `null` until there is a revision and
 * a job to show. */
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

/** The parts of a template that Marigold's prepared maps depend on, as a
 * comparable string; `null` for anything not rendered by Marigold. */
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

/** The masks a placement's saved strokes started from, oldest first -- none
 * when the histories were read at another revision. */
export function undoBases(
  histories: { revision: string; values: Record<string, MaskHistory> },
  revision: string,
  id: string | null,
): string[] {
  if (histories.revision !== revision) return [];
  return histories.values[id ?? "implicit"]?.strokes.map((s) => s.before) ?? [];
}

/** Whether Undo has anything to take back: a stroke drawn since the save,
 * or a saved one (`undoCount`) the draft has not already undone -- none once
 * the draft resets to the automatic mask. */
export function canUndoMask(draft: ReturnType<typeof maskDraft>, undoCount: number): boolean {
  if (draft.strokes.length > 0) return true;
  return !draft.automatic && undoCount > draft.undoSaved;
}

/** Why the preview tab cannot render yet, or `null` when it can. */
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
