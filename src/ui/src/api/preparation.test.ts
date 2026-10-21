import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { prepareTemplate } from "./preparation";

vi.mock("./client", () => ({ api: { POST: vi.fn() } }));
afterEach(() => vi.resetAllMocks());

const request: Parameters<typeof prepareTemplate>[0] = {
  template: "tee",
  config_revision: "revision",
  request_id: "prepare",
  action: "prepare",
  reset_masks_for_photo: false,
};
describe("prepareTemplate", () => {
  it.each([
    {
      detail: {
        reason: "preparation_refused",
        message: "Select Marigold before preparing this template",
      },
      expected: "Select Marigold before preparing this template",
    },
    {
      detail: "Calibration changed; reload before preparing",
      expected: "Calibration changed; reload before preparing",
    },
  ])("preserves the server refusal: $expected", async ({ detail, expected }) => {
    vi.mocked(api.POST).mockResolvedValue({
      error: { detail },
      response: new Response(null, { status: 409 }),
    } as never);
    await expect(prepareTemplate(request)).rejects.toThrow(expected);
  });
  it.each([undefined, { detail: [{ msg: "invalid" }] }, { detail: { message: 5 } }])(
    "handles an unrecognized error body",
    async (error) => {
      vi.mocked(api.POST).mockResolvedValue({ error } as never);
      await expect(prepareTemplate(request)).rejects.toThrow(
        "Preparation could not start. Try again.",
      );
    },
  );
});
