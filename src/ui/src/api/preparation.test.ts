import { afterEach, describe, expect, it, vi } from "vitest";
import { must } from "../test/helpers";

/** The generated client's requests, answered with real `Response`s (see
 * calibrator.test.ts for why `fetch` and `Request` are stubbed). */
const sent: Request[] = [];

function answering(status: number, body: string | null) {
  sent.length = 0;
  vi.stubGlobal(
    "Request",
    class extends Request {
      constructor(input: RequestInfo | URL, init?: RequestInit) {
        super(typeof input === "string" ? new URL(input, "http://ui.test") : input, init);
      }
    },
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      sent.push(request);
      return new Response(body, { status, headers: { "Content-Type": "application/json" } });
    }),
  );
  vi.resetModules();
  return import("./preparation");
}

afterEach(() => vi.unstubAllGlobals());

const request = {
  template: "tee",
  config_revision: "revision",
  request_id: "prepare",
  action: "prepare",
  reset_masks_for_photo: false,
} as const;

async function expectPosted() {
  expect(sent).toHaveLength(1);
  const posted = must(sent[0]);
  expect([posted.method, new URL(posted.url).pathname]).toEqual(["POST", "/api/preparation/jobs"]);
  expect(await posted.json()).toEqual(request);
}

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
    const { prepareTemplate } = await answering(409, JSON.stringify({ detail }));

    await expect(prepareTemplate(request)).rejects.toThrow(expected);
    await expectPosted();
  });

  it.each([
    null,
    JSON.stringify({ detail: [{ msg: "invalid" }] }),
    JSON.stringify({ detail: { message: 5 } }),
  ])("handles an unrecognized error body: %s", async (body) => {
    const { prepareTemplate } = await answering(409, body);

    await expect(prepareTemplate(request)).rejects.toThrow(
      "Preparation could not start. Try again.",
    );
    await expectPosted();
  });
});
