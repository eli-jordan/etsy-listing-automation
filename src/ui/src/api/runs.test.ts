import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { RunsApiError, cancelRun } from "./runs";

function answer(status: number, error?: unknown) {
  return { data: undefined, error, response: new Response(null, { status }) } as never;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("cancelRun", () => {
  it("is true once the run is cancelled", async () => {
    vi.spyOn(api, "DELETE").mockResolvedValue(answer(204));

    await expect(cancelRun("run-1")).resolves.toBe(true);
  });

  it("is false, not an error, when the run finished first", async () => {
    vi.spyOn(api, "DELETE").mockResolvedValue(answer(409, { detail: "finished" }));

    await expect(cancelRun("run-1")).resolves.toBe(false);
  });

  it("throws for any other failure", async () => {
    vi.spyOn(api, "DELETE").mockResolvedValue(answer(404, { detail: "no run" }));

    await expect(cancelRun("run-1")).rejects.toBeInstanceOf(RunsApiError);
  });
});
