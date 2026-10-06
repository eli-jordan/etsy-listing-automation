import type { Preparation } from "../api/preparation";
import type { BoundingBox, SingleTemplate, Renderer } from "../types";
export const MARIGOLD: Extract<Renderer, { type: "marigold" }> = {
  type: "marigold",
  config: {
    appearance: {
      lighting_source: "estimated",
      lighting_strength: 1,
      fabric_texture: 0.25,
      print_shine: 0,
    },
    inference: { num_inference_steps: 10, ensemble_size: 3 },
  },
};
export const BOX: BoundingBox = [
  { x: 10, y: 20 },
  { x: 110, y: 20 },
  { x: 110, y: 120 },
  { x: 10, y: 120 },
];
export const SINGLE: SingleTemplate = {
  kind: "single",
  colour: null,
  artwork: null,
  bounding_box: BOX,
  renderer: MARIGOLD,
};
export const READY: Preparation = {
  template: "tee",
  config_revision: "sha256:revision",
  main_photo: "mockup-templates/tee/main.png",
  maps: { state: "ready", reason: null, message: null, can_render: true, content_digest: "maps-1" },
  placements: [{ placement_id: null, mask_available: true, mask_reason: null, undo_count: 0 }],
  active_job: null,
  latest_job: null,
  renderer_settings: {},
  prepared_engine: null,
};
