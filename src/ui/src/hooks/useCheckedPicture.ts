import { useEffect, useState } from "react";
import { scenePreviewChanged } from "../api/listings";

/**
 * `url`, or -- once the server says the scene it served there was found under
 * a stale remembered digest -- the same picture asked for again.
 *
 * A listing scene loads at once from the digests the server kept across a
 * restart, and is checked behind it: almost always the answer is "unchanged"
 * and nothing happens. Only the picture on screen is checked, so walking the
 * gallery asks once per picture shown.
 */
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
