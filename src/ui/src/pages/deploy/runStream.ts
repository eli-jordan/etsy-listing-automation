import { runEventsUrl } from "../../api/runs";
import { type EventStreamHandle, type EventStreamOptions, openEventStream } from "../../api/sse";
import type { RunEvent } from "../../types";

export type RunStreamOptions = EventStreamOptions<RunEvent>;
export type RunStreamHandle = EventStreamHandle;

export function openRunStream(runId: string, options: RunStreamOptions): RunStreamHandle {
  return openEventStream(runEventsUrl(runId), options);
}
