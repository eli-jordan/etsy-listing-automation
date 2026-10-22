import { afterEach, expect, it, vi } from "vitest";
import type { Middleware } from "openapi-fetch";
import { api } from "./client";
import { getTemplateConfig } from "./calibrator";
import { getMaskHistory, getPreparation } from "./preparation";
import { READY, SINGLE } from "../test/marigold";

// Node requires absolute Request URLs; browsers resolve the app's relative paths.
vi.hoisted(() => {
  class BrowserRequest extends Request {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(typeof input === "string" ? new URL(input, "http://localhost") : input, init);
    }
  }
  vi.stubGlobal("Request", BrowserRequest);
});
const requests: Request[] = [];
const transport: Middleware = {
  onRequest({ request }) {
    requests.push(request);
    const body = request.url.endsWith("/config")
      ? SINGLE
      : request.url.endsWith("/preparation")
        ? READY
        : { checksum: "mask", undo_count: 0, strokes: [] };
    return Response.json(body, {
      headers: {
        ETag: '"current"',
        "Last-Modified": "Wed, 17 Sep 2026 18:30:00 GMT",
      },
    });
  },
};
afterEach(() => {
  api.eject(transport);
  requests.length = 0;
  vi.unstubAllGlobals();
});

it("bypasses previously cached calibration documents and mutable preparation state", async () => {
  api.use(transport);
  const name = "tee";
  // openapi-fetch's generated paths are relative in production. Its transport
  // hook receives the Request before it reaches the browser's HTTP cache.
  await getTemplateConfig(name);
  await getPreparation(name);
  await getMaskHistory(name, null);
  await getMaskHistory(name, "front");
  expect(requests).toHaveLength(4);
  expect(requests.every((request) => request.cache === "no-store")).toBe(true);
});
