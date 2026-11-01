/** What has come back for a preview request. Stamped with the request's key
 * so a count from this run can never appear beside tiles from the last one. */
export interface PreviewResult {
  key: string;
  rendered: Record<string, string>;
  done: number;
  failed: number;
}

/** Where a preview run stands against the config the editor holds now
 * (`key`). */
export function previewProgress(
  request: { key: string; jobs: readonly unknown[] } | null,
  result: PreviewResult | null,
  key: string,
) {
  const rendered = result?.key === request?.key ? (result?.rendered ?? {}) : {};
  const done = result?.done ?? 0;
  const failed = result?.failed ?? 0;
  // A run for an older config. Its images are still the last full-size renders
  // there are, and worth looking at -- they are just no longer of what the
  // editor is holding, and saying so is the stale banner's whole job.
  const stale = request !== null && request.key !== key;
  const complete = request !== null && done + failed >= request.jobs.length;
  // Everything asked for has come back, and it is a picture of what the editor
  // currently holds -- the only state in which approving means anything.
  const approvable = complete && !stale && failed === 0;
  return { rendered, done, failed, stale, complete, approvable };
}
