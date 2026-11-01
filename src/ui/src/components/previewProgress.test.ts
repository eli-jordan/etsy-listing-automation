import { describe, expect, it } from "vitest";
import { previewProgress } from "./previewProgress";

const run = (key: string, jobs = 2) => ({ key, jobs: Array.from({ length: jobs }) });

describe("previewProgress", () => {
  it("has nothing rendered and nothing to approve before the first request", () => {
    expect(previewProgress(null, null, "a")).toEqual({
      rendered: {},
      done: 0,
      failed: 0,
      stale: false,
      complete: false,
      approvable: false,
    });
  });

  it("is approvable once every job of the current request rendered", () => {
    const result = { key: "a", rendered: { x: "u1", y: "u2" }, done: 2, failed: 0 };
    expect(previewProgress(run("a"), result, "a")).toEqual({
      rendered: { x: "u1", y: "u2" },
      done: 2,
      failed: 0,
      stale: false,
      complete: true,
      approvable: true,
    });
  });

  it("is complete but not approvable when a job failed", () => {
    const result = { key: "a", rendered: { x: "u1" }, done: 1, failed: 1 };
    const progress = previewProgress(run("a"), result, "a");
    expect(progress.complete).toBe(true);
    expect(progress.approvable).toBe(false);
  });

  it("is stale, and never approvable, when the editor has moved on", () => {
    const result = { key: "a", rendered: { x: "u1", y: "u2" }, done: 2, failed: 0 };
    const progress = previewProgress(run("a"), result, "b");
    expect(progress.stale).toBe(true);
    expect(progress.complete).toBe(true);
    expect(progress.approvable).toBe(false);
    expect(progress.rendered).toEqual({ x: "u1", y: "u2" });
  });

  it("shows no tiles from a result stamped for another request", () => {
    const result = { key: "old", rendered: { x: "u1" }, done: 1, failed: 0 };
    const progress = previewProgress(run("a"), result, "a");
    expect(progress.rendered).toEqual({});
    expect(progress.complete).toBe(false);
  });
});
