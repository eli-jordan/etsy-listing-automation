import { useEffect } from "react";

/** Pictures fetched at once. Each full-size scene the server has not cached
 * yet is composed on the request's own thread, so this is also how many
 * compositions a preload holds open; two leaves room for the one the seller
 * clicks. */
export const PRELOAD_CONCURRENCY = 2;

/**
 * Fetch every picture in `urls` into the browser's HTTP cache, in list
 * order, {@link PRELOAD_CONCURRENCY} at a time, so showing one later is a
 * local decode rather than a full-size render and download.
 *
 * The bodies are read and dropped, not kept decoded: a full-size scene is
 * 15-20 MB decoded and a garment profile has dozens of colours. A picture
 * that fails is skipped -- its click is just as slow as it was without the
 * preload. A new list (by content, not array identity) abandons the old one.
 */
export function usePreloadedPictures(urls: readonly string[]): void {
  // Joined, so an equal list in a new array (every render of a parent that
  // derives it) does not restart the preload.
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
