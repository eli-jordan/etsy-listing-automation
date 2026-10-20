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
      config_revision: "sha256:revision",
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
    const { result, unmount, rerender } = renderHook(
      ({ pending }) => usePreparation("tee", 0, pending),
      { initialProps: { pending: false } },
    );
    await waitFor(() => expect(result.current.preparation?.active_job?.id).toBe("job"));
    expect(submit).not.toHaveBeenCalled();
    vi.useFakeTimers();
    act(() => {
      for (let sequence = 4; sequence <= 8; sequence++)
        options?.onEvent({ ...job, job_id: job.id, sequence });
    });
    expect(get).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(follow).toHaveBeenLastCalledWith("job", expect.objectContaining({ lastEventId: 8 }));
    act(() => options?.onError?.(new Error("drop")));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(get).toHaveBeenCalledTimes(3);
    expect(submit).not.toHaveBeenCalled();
    rerender({ pending: true });
    expect(close).toHaveBeenCalled();
    act(() => options?.onEvent({ ...job, job_id: job.id, sequence: 9 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(get).toHaveBeenCalledTimes(3);
    rerender({ pending: false });
    await act(async () => {});
    expect(get).toHaveBeenCalledTimes(4);
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

it("retains idle readiness without decoding it repeatedly and refreshes on focus", async () => {
  vi.useFakeTimers();
  const get = vi.spyOn(api, "getPreparation").mockResolvedValue(READY);
  const { result } = renderHook(() => usePreparation("tee", 0));
  await act(async () => {});
  expect(result.current.preparation).toEqual(READY);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(12000);
  });
  expect(get).toHaveBeenCalledTimes(1);
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(get).toHaveBeenCalledTimes(2);
});

it("defers automatic readiness reads while a composite is pending and resumes fresh", async () => {
  vi.useFakeTimers();
  const get = vi.spyOn(api, "getPreparation").mockResolvedValue(READY);
  const { result, rerender } = renderHook(({ pending }) => usePreparation("tee", 0, pending), {
    initialProps: { pending: false },
  });
  await act(async () => {});
  expect(result.current.preparation).toEqual(READY);
  rerender({ pending: true });
  await act(async () => {
    window.dispatchEvent(new Event("focus"));
    result.current.reload();
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(get).toHaveBeenCalledTimes(1);
  expect(result.current.preparation).toEqual(READY);
  get.mockResolvedValue({ ...READY, config_revision: "sha256:new-revision" });
  rerender({ pending: false });
  await act(async () => {});
  expect(get).toHaveBeenCalledTimes(2);
  expect(result.current.preparation?.config_revision).toBe("sha256:new-revision");
});
