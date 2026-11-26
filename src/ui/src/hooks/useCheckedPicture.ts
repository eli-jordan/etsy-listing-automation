import { useEffect, useState } from "react";
import { scenePreviewChanged } from "../api/listings";

/** `url`, or the same picture asked for again once the server says the scene
 * it served there came from stale remembered digests. Only the picture on
 * screen is checked. */
export function useCheckedPicture(url: string): string {
  const [stale, setStale] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    scenePreviewChanged(url)
      .then((changed) => {
        if (current && changed) setStale(url);
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [url]);
  return stale === url ? `${url}&checked=1` : url;
}
