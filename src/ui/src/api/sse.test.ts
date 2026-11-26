import { afterEach, describe, expect, it, vi } from "vitest";
import { openEventStream } from "./sse";

/** A response body the test writes chunk by chunk, then ends. */
function streamed() {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start: (c) => {
      controller = c;
    },
  });
  return {
    response: new Response(body, { status: 200 }),
    write: (text: string) => controller.enqueue(encoder.encode(text)),
    end: () => controller.close(),
  };
}

const frame = (n: number) => `id: ${n}\nevent: step\ndata: {"n":${n}}\n\n`;

async function settled() {
  for (let turn = 0; turn < 10; turn += 1) await new Promise((resolve) => setTimeout(resolve, 0));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("openEventStream", () => {
  it("delivers a frame split across chunks only once it is whole", async () => {
    const body = streamed();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => body.response),
    );
    const onEvent = vi.fn();
    openEventStream("/api/runs/1/events", { onEvent });

    const whole = frame(1) + frame(2);
    body.write(whole.slice(0, 20));
    await settled();
    expect(onEvent).not.toHaveBeenCalled();

    body.write(whole.slice(20, frame(1).length + 5));
    await settled();
    expect(onEvent.mock.calls).toEqual([[{ n: 1 }]]);

    body.write(whole.slice(frame(1).length + 5));
    await settled();
    expect(onEvent.mock.calls).toEqual([[{ n: 1 }], [{ n: 2 }]]);
  });

  it("reports the end of the run as done, not as an error", async () => {
    const body = streamed();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => body.response),
    );
    const onDone = vi.fn();
    const onError = vi.fn();
    openEventStream("/api/runs/1/events", { onEvent: vi.fn(), onDone, onError });

    body.write(frame(1));
    body.end();
    await settled();

    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
  });

  it("reports a refused request as an error, not as done", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("gone", { status: 404 })),
    );
    const onDone = vi.fn();
    const onError = vi.fn();
    openEventStream("/api/runs/1/events", { onEvent: vi.fn(), onDone, onError });
    await settled();

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onDone).not.toHaveBeenCalled();
  });

  it("asks to resume after the last event seen", async () => {
    const fetch = vi.fn(async () => streamed().response);
    vi.stubGlobal("fetch", fetch);
    openEventStream("/api/runs/1/events", { onEvent: vi.fn(), lastEventId: 7 });

    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/1/events",
      expect.objectContaining({ headers: { "Last-Event-ID": "7" } }),
    );
  });

  it("can be closed twice, and after the stream has finished, without an error", async () => {
    const body = streamed();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => body.response),
    );
    const onError = vi.fn();
    const stream = openEventStream("/api/runs/1/events", { onEvent: vi.fn(), onError });

    body.end();
    await settled();
    stream.close();
    stream.close();
    await settled();

    expect(onError).not.toHaveBeenCalled();
  });
});
