/** "Saved 2 mins ago" doesn't need to be precise -- coarse buckets read as
 * true for longer, so nobody watches "Saved 1 minute ago" tick to "2" every
 * refresh. */
export function timeAgo(savedAt: number, now: number): string {
  const seconds = Math.max(0, Math.round((now - savedAt) / 1000));
  if (seconds < 60) return "a moment ago";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hr${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}
