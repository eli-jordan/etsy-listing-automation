import { useEffect } from "react";

/** The server composes an uncached scene on the request's thread: two leaves room for a click. */
export const PRELOAD_CONCURRENCY = 2;

/** Into the browser's HTTP cache only: a full-size scene is 15-20 MB decoded. */
export function usePreloadedPictures(urls: readonly string[]): void {
  const key = urls.join("\n");
  useEffect(() => {
    const controller = new AbortController();
    void preload(key === "" ? [] : key.split("\n"), controller.signal);
    return () => controller.abort();
  }, [key]);
}

async function preload(urls: string[], signal: AbortSignal): Promise<void> {
  let next = 0;
  async function worker(): Promise<void> {
    for (let url = urls[next]; !signal.aborted && url !== undefined; url = urls[next]) {
      next += 1;
      await fetchQuietly(url, signal);
    }
  }
  await Promise.all(Array.from({ length: Math.min(PRELOAD_CONCURRENCY, urls.length) }, worker));
}

async function fetchQuietly(url: string, signal: AbortSignal): Promise<void> {
  try {
    const response = await fetch(url, { signal });
    // The cache entry is complete only once the body has been read.
    await response.arrayBuffer();
  } catch {
    // Aborted, or a picture the server refused: nothing to preload.
  }
}
