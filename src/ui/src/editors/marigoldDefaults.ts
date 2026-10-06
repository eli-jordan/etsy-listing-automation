import type { Renderer } from "../types";
export const MARIGOLD_DEFAULTS: Extract<Renderer, { type: "marigold" }> = {
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
