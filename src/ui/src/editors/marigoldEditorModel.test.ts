import { describe, expect, it } from "vitest";
import type { BoundingBox, TemplateConfigState } from "../types";
import { MARIGOLD_DEFAULTS } from "./marigoldDefaults";
import {
  editorPlacements,
  editorPreviewRequest,
  canUndoMask,
  marigoldMapInputs,
  previewBlocker,
  previewJobs,
  undoBases,
} from "./marigoldEditorModel";

const box: BoundingBox = [
  { x: 0, y: 0 },
  { x: 10, y: 0 },
  { x: 10, y: 10 },
  { x: 0, y: 10 },
];

const single = {
  kind: "single",
  colour: "Black",
  bounding_box: box,
  renderer: MARIGOLD_DEFAULTS,
} as unknown as TemplateConfigState;
const matrix = { ...single, kind: "colour-matrix" } as unknown as TemplateConfigState;
const multiple = {
  kind: "multiple",
  placements: [{ id: "front", colour: "White", bounding_box: box }],
  renderer: MARIGOLD_DEFAULTS,
} as unknown as TemplateConfigState;

describe("editorPlacements", () => {
  it("uses a multiple template's own placements", () => {
    expect(editorPlacements(multiple, ["Red"])).toEqual([
      { id: "front", colour: "White", bounding_box: box },
    ]);
  });

  it("gives a single template one implicit placement in its colour", () => {
    expect(editorPlacements(single, ["Red"])).toEqual([
      { id: "implicit", colour: "Black", bounding_box: box },
    ]);
  });

  it("gives a colour matrix one implicit placement in its first colour", () => {
    expect(editorPlacements(matrix, ["Red", "Blue"])).toEqual([
      { id: "implicit", colour: "Red", bounding_box: box },
    ]);
    expect(editorPlacements(matrix, [])[0]?.colour).toBe("");
  });
});

describe("previewJobs", () => {
  it("renders a colour matrix once per colour", () => {
    expect(previewJobs(matrix, ["Red", "Blue"], "tee").map((job) => job.id)).toEqual([
      "Red",
      "Blue",
    ]);
  });

  it("renders a multiple template once, with every placement", () => {
    expect(previewJobs(multiple, [], "tee")).toEqual([
      {
        id: "tee",
        label: "tee",
        body: {
          placements: [{ id: "front", colour: "White", bounding_box: box }],
          renderer: MARIGOLD_DEFAULTS,
        },
      },
    ]);
  });

  it("renders a single template once, with its box", () => {
    expect(previewJobs(single, [], "tee")[0]?.body).toEqual({
      bounding_box: box,
      renderer: MARIGOLD_DEFAULTS,
    });
  });
});

describe("marigoldMapInputs", () => {
  it("is null for no config", () => {
    expect(marigoldMapInputs(null)).toBeNull();
  });

  it("changes with geometry but not with colour", () => {
    const moved = { ...single, bounding_box: [...box].reverse() } as TemplateConfigState;
    const recoloured = { ...single, colour: "White" } as TemplateConfigState;
    expect(marigoldMapInputs(moved)).not.toBe(marigoldMapInputs(single));
    expect(marigoldMapInputs(recoloured)).toBe(marigoldMapInputs(single));
  });
});

describe("undoBases", () => {
  const histories = {
    revision: "r1",
    values: { implicit: { strokes: [{ before: "a" }, { before: "b" }] } },
  } as never;

  it("lists the saved strokes' bases for the current revision", () => {
    expect(undoBases(histories, "r1", null)).toEqual(["a", "b"]);
  });

  it("is empty for another revision or an unknown placement", () => {
    expect(undoBases(histories, "r2", null)).toEqual([]);
    expect(undoBases(histories, "r1", "front")).toEqual([]);
  });
});

describe("previewBlocker", () => {
  const ready = {
    mapsReady: true,
    unsavedMaps: false,
    awaitingSavedRevision: false,
    activeJob: false,
    mapsMessage: undefined,
  };

  it("lets a ready, saved template render", () => {
    expect(previewBlocker(ready)).toBeNull();
  });

  it("asks for a save first", () => {
    expect(previewBlocker({ ...ready, unsavedMaps: true, mapsReady: false })).toBe(
      "Save your calibration changes before rendering.",
    );
  });

  it("waits for the saved revision", () => {
    expect(previewBlocker({ ...ready, awaitingSavedRevision: true })).toBe(
      "Waiting for current calibration status. Reload the template if it changed elsewhere.",
    );
  });

  it("names the maps' own reason, or asks for preparation", () => {
    expect(previewBlocker({ ...ready, mapsReady: false, mapsMessage: "Maps are stale." })).toBe(
      "Maps are stale.",
    );
    expect(previewBlocker({ ...ready, activeJob: true })).toBe("Prepare the template first.");
  });
});

describe("editorPreviewRequest", () => {
  const jobs = previewJobs(matrix, ["Red", "Blue"], "tee");

  it("previews the chosen colour at the calibration revision, with unsaved masks", () => {
    expect(editorPreviewRequest("colour-matrix", jobs, "Blue", "r1", ["cosy"], [])).toEqual({
      ...jobs[1]?.body,
      calibration_revision: "r1",
      labels: ["cosy"],
      mask_edits: [],
    });
  });

  it("previews the only job of other kinds", () => {
    const one = previewJobs(single, [], "tee");
    expect(editorPreviewRequest("single", one, "", "r1", [], [])?.calibration_revision).toBe("r1");
  });

  it("asks for nothing without a revision or a body", () => {
    expect(editorPreviewRequest("colour-matrix", jobs, "Blue", "", [], [])).toBeNull();
    expect(editorPreviewRequest("colour-matrix", jobs, "Green", "r1", [], [])).toBeNull();
  });
});

describe("canUndoMask", () => {
  const draft = { automatic: false, strokes: [], undoSaved: 0 };

  it("undoes an unsaved stroke first", () => {
    expect(canUndoMask({ ...draft, strokes: [{} as never] }, 0)).toBe(true);
  });

  it("undoes saved strokes the draft has not already undone", () => {
    expect(canUndoMask(draft, 2)).toBe(true);
    expect(canUndoMask({ ...draft, undoSaved: 2 }, 2)).toBe(false);
  });

  it("has no saved strokes to undo once the draft resets to the automatic mask", () => {
    expect(canUndoMask({ ...draft, automatic: true }, 2)).toBe(false);
  });
});
