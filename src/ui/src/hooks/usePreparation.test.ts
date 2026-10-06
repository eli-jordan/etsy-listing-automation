import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/preparation";
import { READY } from "../test/marigold";
import { usePreparation } from "./usePreparation";
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});
describe("usePreparation", () => {
  it("reattaches to existing work and reconnects without submitting a job", async () => {
    const job: api.PreparationJob = {
      id: "job",
      template: "tee",
      kind: "prepare",
      phase: "running",
      step: "normals",
      elapsed: 3,
      placements_completed: 0,
      placements_total: 1,
      error: null,
      last_event_sequence: 3,
      queue_position: null,
      engine_version: "engine",
    };
    const get = vi.spyOn(api, "getPreparation").mockResolvedValue({ ...READY, active_job: job });
    const submit = vi.spyOn(api, "prepareTemplate");
    let options: Parameters<typeof api.followPreparation>[1] | undefined;
    const close = vi.fn();
    const follow = vi.spyOn(api, "followPreparation").mockImplementation((_id, value) => {
      options = value;
      return { close };
    });
    const { result, unmount } = renderHook(() => usePreparation("tee", 0));
    await waitFor(() => expect(result.current.preparation?.active_job?.id).toBe("job"));
    expect(submit).not.toHaveBeenCalled();
    vi.useFakeTimers();
    act(() => options?.onEvent({ ...job, job_id: job.id, sequence: 4 }));
    await act(async () => {});
    expect(follow).toHaveBeenLastCalledWith("job", expect.objectContaining({ lastEventId: 4 }));
    act(() => options?.onError?.(new Error("drop")));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(get).toHaveBeenCalledTimes(3);
    expect(submit).not.toHaveBeenCalled();
    unmount();
    expect(close).toHaveBeenCalled();
  });
  it("discards a late status response after switching template", async () => {
    let finish!: (v: api.Preparation) => void;
    vi.spyOn(api, "getPreparation").mockImplementation((name) =>
      name === "old"
        ? new Promise((r) => {
            finish = r;
          })
        : Promise.resolve({ ...READY, template: name }),
    );
    const { result, rerender } = renderHook(({ name }) => usePreparation(name, 0), {
      initialProps: { name: "old" },
    });
    rerender({ name: "new" });
    await waitFor(() => expect(result.current.preparation?.template).toBe("new"));
    await act(async () => finish({ ...READY, template: "old" }));
    expect(result.current.preparation?.template).toBe("new");
  });
});
