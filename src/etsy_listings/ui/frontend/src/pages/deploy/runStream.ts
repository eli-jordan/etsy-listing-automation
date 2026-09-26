import { runEventsUrl } from "../../api/runs";
import { type EventStreamHandle, type EventStreamOptions, openEventStream } from "../../api/sse";
import type { RunEvent } from "../../types";

/**
 * A typed reader over `GET /api/runs/{id}/events` (A33 decision 7's SSE
 * route), with `Last-Event-ID` resume (docs/deploy-changes.md decision 9:
 * reattaching sends "the SSE stream with the last event id"). The reader
 * itself is `api/sse.ts`'s, shared with AI runs; its docstring says why it
 * is `fetch` and not `EventSource`.
 */

export type RunStreamOptions = EventStreamOptions<RunEvent>;
export type RunStreamHandle = EventStreamHandle;

export function openRunStream(runId: string, options: RunStreamOptions): RunStreamHandle {
  return openEventStream(runEventsUrl(runId), options);
}
