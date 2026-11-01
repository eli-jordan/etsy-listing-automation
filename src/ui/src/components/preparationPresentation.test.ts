import { expect, it } from "vitest";
import { READY } from "../test/marigold";
import {
  activePreparationStep,
  preparationAction,
  prepareButtonLabel,
  mapStatusClass,
} from "./preparationPresentation";

it.each([
  ["loading_models", -1],
  ["normals", 0],
  ["lighting", 1],
  ["depth", 2],
  ["building_maps", 3],
  ["bake", 3],
  ["normals_depth", 0],
])("shows the active step for %s", (step, expected) => {
  expect(activePreparationStep(step)).toBe(expected);
});

it("prioritizes failed preparation over changed photos and ready maps", () => {
  expect(preparationAction(null)).toBe("prepare");
  expect(preparationAction(READY)).toBe("prepare_again");
  const changed = { ...READY, maps: { ...READY.maps, reason: "photo_changed" } };
  expect(preparationAction(changed)).toBe("prepare_again");
  expect(
    preparationAction({
      ...changed,
      latest_job: {
        id: "job",
        template: "tee",
        kind: "prepare",
        phase: "failed",
        step: "normals",
        elapsed: 1,
        placements_completed: 0,
        placements_total: 1,
        config_revision: "revision",
        error: "failed",
        last_event_sequence: 1,
        queue_position: null,
        engine_version: "engine",
      },
    }),
  ).toBe("retry");
});

it.each([
  ["retry", true, "Retry preparation"],
  ["prepare_again", true, "Reset masks and prepare"],
  ["prepare_again", false, "Prepare again"],
  ["prepare", false, "Prepare template"],
] as const)("labels %s with photo recovery %s", (action, recovery, expected) => {
  expect(prepareButtonLabel(action, recovery)).toBe(expected);
});

it("keeps the existing map status classes", () => {
  expect(mapStatusClass("Ready")).toBe(" mg-status--ready");
  expect(mapStatusClass("Failed")).toBe(" mg-status--failed");
  expect(mapStatusClass("Preparing")).toBe("");
});
