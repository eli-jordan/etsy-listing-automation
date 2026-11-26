export interface PreviewResult {
  key: string;
  rendered: Record<string, string>;
  done: number;
  failed: number;
}

export function previewProgress(
  request: { key: string; jobs: readonly unknown[] } | null,
  result: PreviewResult | null,
  key: string,
) {
  const rendered = result?.key === request?.key ? (result?.rendered ?? {}) : {};
  const done = result?.done ?? 0;
  const failed = result?.failed ?? 0;
  // A run for an older config: its images are still worth looking at, and the
  // stale banner says they are no longer of what the editor holds.
  const stale = request !== null && request.key !== key;
  const complete = request !== null && done + failed >= request.jobs.length;
  const approvable = complete && !stale && failed === 0;
  return { rendered, done, failed, stale, complete, approvable };
}
