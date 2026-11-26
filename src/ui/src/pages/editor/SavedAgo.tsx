import { useNow } from "../../hooks/useNow";
import { timeAgo } from "./timeAgo";

export function SavedAgo({ savedAt }: { savedAt: number }) {
  const now = useNow();
  return <>Saved {timeAgo(savedAt, now)}</>;
}
