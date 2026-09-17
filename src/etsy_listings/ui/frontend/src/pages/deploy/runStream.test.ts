import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { openRunStream } from "./runStream";

/**
 * `GET /api/runs/{id}/events` through a plain `fetch` reader, framed exactly
 * as `ui/api/runs.py`'s `_sse_frame` writes: `id: <n>\nevent: <type>\ndata:
 * <json>\n\n`. `fetch` is stubbed with a real `ReadableStream` so the parser
 * is exercised against actual chunk boundaries, not a fake that hands back
 * whole frames for free.
 */

function sseBody(frames: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let index = 0;
  return new ReadableStream({
    pull(controller) {
      if (index >= frames.length) {
        controller.close();
        return;
      }
      controller.enqueue(encoder.encode(frames[index]));
      index++;
    },
  });
}

function frame(id: number, type: string, data: Record<string, unknown>): string {
  return `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify({ id, type, ...data })}\n\n`;
}

describe("openRunStream", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("parses every frame in the stream, in order, and reports when it ends", async () => {
    const body = sseBody([
      frame(1, "phase", { phase: "queued" }),
      frame(2, "phase", { phase: "planning" }),
    ]);
    fetchMock.mockResolvedValue(new Response(body, { status: 200 }));

    const events: unknown[] = [];
    let done = false;
    openRunStream("run-1", {
      onEvent: (e) => events.push(e),
      onDone: () => {
        done = true;
      },
    });

    await vi.waitFor(() => expect(done).toBe(true));

    expect(events).toEqual([
      { id: 1, type: "phase", phase: "queued" },
      { id: 2, type: "phase", phase: "planning" },
    ]);
  });

  it("parses a frame split across two chunks", async () => {
    const whole = frame(1, "phase", { phase: "ready" });
    const splitAt = Math.floor(whole.length / 2);
    const body = sseBody([whole.slice(0, splitAt), whole.slice(splitAt)]);
    fetchMock.mockResolvedValue(new Response(body, { status: 200 }));

    const events: unknown[] = [];
    openRunStream("run-2", { onEvent: (e) => events.push(e) });

    await vi.waitFor(() => expect(events).toHaveLength(1));
    expect(events[0]).toEqual({ id: 1, type: "phase", phase: "ready" });
  });

  it("sends Last-Event-ID when reattaching after a known event", async () => {
    fetchMock.mockResolvedValue(new Response(sseBody([]), { status: 200 }));

    openRunStream("run-3", { lastEventId: 7, onEvent: () => {} });

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/runs/run-3/events");
    expect((init.headers as Record<string, string>)["Last-Event-ID"]).toBe("7");
  });

  it("sends no Last-Event-ID for a run just started", async () => {
    fetchMock.mockResolvedValue(new Response(sseBody([]), { status: 200 }));

    openRunStream("run-4", { onEvent: () => {} });

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.headers).toEqual({});
  });

  it("reports an HTTP error instead of silently doing nothing", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 404 }));

    let error: unknown = null;
    openRunStream("run-5", { onEvent: () => {}, onError: (e) => (error = e) });

    await vi.waitFor(() => expect(error).not.toBeNull());
  });

  it("close() aborts the underlying request without calling onError", async () => {
    const body = sseBody([]);
    fetchMock.mockImplementation((_url: string, init: RequestInit) => {
      return new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
      });
    });

    let errored = false;
    const handle = openRunStream("run-6", {
      onEvent: () => {},
      onError: () => {
        errored = true;
      },
    });
    handle.close();

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    // Give the rejected promise's microtask a turn.
    await new Promise((r) => setTimeout(r, 0));
    expect(errored).toBe(false);
    void body;
  });
});
