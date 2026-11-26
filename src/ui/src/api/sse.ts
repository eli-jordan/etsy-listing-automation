/**
 * A typed `text/event-stream` reader over `fetch`. Not `EventSource`: it cannot
 * send `Last-Event-ID` on its first request, which reattaching to a run this
 * page did not start needs. A dropped stream is not reopened; a reload reattaches.
 */

export interface EventStreamOptions<Event> {
  lastEventId?: number;
  onEvent: (event: Event) => void;
  onDone?: () => void;
  onError?: (error: unknown) => void;
}

export interface EventStreamHandle {
  close: () => void;
}

function parseFrame<Event>(block: string): Event | null {
  let data: string | null = null;
  for (const line of block.split("\n")) {
    if (line.startsWith("data: ")) data = line.slice("data: ".length);
  }
  if (data === null) return null;
  return JSON.parse(data) as Event;
}

async function readFrames<Event>(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent: (event: Event) => void,
): Promise<void> {
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    const partialFrame = frames.pop() ?? "";
    buffer = partialFrame;
    for (const block of frames) {
      const event = parseFrame<Event>(block);
      if (event !== null) onEvent(event);
    }
  }
}

export function openEventStream<Event>(
  url: string,
  options: EventStreamOptions<Event>,
): EventStreamHandle {
  const controller = new AbortController();
  const headers =
    options.lastEventId !== undefined ? { "Last-Event-ID": String(options.lastEventId) } : {};

  async function read(): Promise<void> {
    let response: Response;
    try {
      response = await fetch(url, { headers, signal: controller.signal });
    } catch (error) {
      if (!controller.signal.aborted) options.onError?.(error);
      return;
    }
    if (!response.ok || response.body === null) {
      if (!controller.signal.aborted)
        options.onError?.(new Error(`event stream: HTTP ${response.status}`));
      return;
    }

    try {
      await readFrames(response.body.getReader(), options.onEvent);
      options.onDone?.();
    } catch (error) {
      if (!controller.signal.aborted) options.onError?.(error);
    }
  }

  void read();

  return {
    close: () => controller.abort(),
  };
}
