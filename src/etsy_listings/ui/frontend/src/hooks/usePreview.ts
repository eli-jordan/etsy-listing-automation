import { useEffect, useRef, useState } from "react";
import { renderPreview } from "../api/calibrator";

/** How long the editor waits after the last edit before asking the server for
 * a new composite. Dragging a corner fires a change per mouse move, and each
 * preview is a real render -- one request per frame would queue the renderer
 * behind work nobody will look at. */
export const PREVIEW_DEBOUNCE_MS = 200;

type PreviewBody = Parameters<typeof renderPreview>[1];

/**
 * The debounced preview loop, shared by all three editors.
 *
 * Each editor used to carry its own copy of this: the same `setTimeout`,
 * `renderPreview`, revoke-the-previous-URL and `clearTimeout` cleanup, written
 * out three times. All three had the same leak -- the cleanup cleared the
 * timer but never revoked the object URL still held in state, so every
 * template switch and every unmount stranded one blob in the document. There
 * is one implementation now, and it revokes on the way out.
 *
 * `body` is compared by value, not identity: an editor rebuilds it on every
 * render, and comparing by identity would restart the debounce on renders that
 * changed nothing the preview depends on. Pass `null` to hold off entirely
 * (a colour-matrix template with no colour selected yet).
 */
export function usePreview(
  templateName: string,
  body: PreviewBody | null,
  design: string,
): string | null {
  const [url, setUrl] = useState<string | null>(null);

  // The URL currently on screen, for the unmount revoke below. A ref, because
  // that cleanup must not re-run every time the URL changes -- it would revoke
  // the image the editor is displaying.
  const current = useRef<string | null>(null);
  useEffect(() => {
    current.current = url;
  }, [url]);
  useEffect(
    () => () => {
      if (current.current) URL.revokeObjectURL(current.current);
    },
    [],
  );

  const key = body === null ? null : JSON.stringify(body);

  useEffect(() => {
    if (key === null) return;
    let live = true;
    const timer = setTimeout(() => {
      renderPreview(templateName, JSON.parse(key) as PreviewBody, design)
        .then((next) => {
          // A response that lands after the editor moved on: revoke it here
          // rather than storing it, or it leaks exactly like the old cleanup
          // let the displayed one leak.
          if (!live) {
            URL.revokeObjectURL(next);
            return;
          }
          setUrl((previous) => {
            if (previous) URL.revokeObjectURL(previous);
            return next;
          });
        })
        .catch(() => {
          /* a failed preview leaves the last good one on screen */
        });
    }, PREVIEW_DEBOUNCE_MS);

    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [templateName, key, design]);

  return url;
}
