import { useNow } from "../../hooks/useNow";
import { timeAgo } from "./timeAgo";

/** Ticks its own clock so "Saved a moment ago" ages into "Saved 2 mins ago"
 * without a new save -- a plain string computed once at render time would
 * freeze at whatever it said when the save happened. */
export function SavedAgo({ savedAt }: { savedAt: number }) {
  const now = useNow();
  return <>Saved {timeAgo(savedAt, now)}</>;
}
