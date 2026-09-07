import { useCallback, useEffect, useRef, useState } from "react";
import { renderPreview } from "../api/calibrator";

/** How long the editor waits after the last edit before asking the server for
 * a new composite.
 *
 * Short, because an editor frame is now a downscaled render off a warm
 * in-process cache rather than a full-resolution one off disk. The debounce is
 * no longer what protects the server -- {@link usePreview}'s one-at-a-time
 * rule is -- it just avoids spending a request on the first pixel of a drag
 * that is about to travel two hundred more. */
export const PREVIEW_DEBOUNCE_MS = 80;

type PreviewBody = Parameters<typeof renderPreview>[1];

interface Job {
  templateName: string;
  key: string;
  design: string;
}

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
 *
 * **One request is in flight at a time.** A drag outruns any debounce short
 * enough to feel live, and firing regardless just queues renders behind each
 * other on a server that runs them one at a time -- which does not make the
 * newest frame arrive sooner, only every frame arrive later, and progressively
 * later as the drag goes on. So a change during a render is *recorded* rather
 * than sent, and the render that finishes immediately starts the latest one
 * instead. Intermediate frames nobody would have seen are dropped, which is
 * the point.
 *
 * Renders at `editor` scale. The image that comes back is therefore smaller
 * than the template's real photo, and must not be measured to find the
 * coordinate space -- see `QuadEditor`'s `space` prop.
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

  // The job waiting to be sent (at most one -- a newer edit overwrites an
  // unsent older one), and whether the loop is already running.
  const queued = useRef<Job | null>(null);
  const busy = useRef(false);
  // Bumped when this hook stops caring about anything already in flight: an
  // unmount, or a switch to a different template. Not bumped for an ordinary
  // edit -- that response is still the newest frame there is, and showing it
  // while the next one renders is what keeps the canvas from flickering back
  // to a stale image.
  const generation = useRef(0);

  // A loop rather than a call that restarts itself: the "render the newest
  // thing that arrived while I was busy" step is the same step as the first
  // one, and writing it as recursion only made the function reference itself
  // before it existed.
  const pump = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      while (queued.current) {
        const job = queued.current;
        queued.current = null;
        const sent = generation.current;
        try {
          const next = await renderPreview(
            job.templateName,
            JSON.parse(job.key) as PreviewBody,
            job.design,
            "editor",
          );
          // A response for a template the editor has already left: revoked
          // here rather than stored, or it leaks exactly like the old cleanup
          // let the displayed one leak.
          if (sent !== generation.current) {
            URL.revokeObjectURL(next);
            continue;
          }
          setUrl((previous) => {
            if (previous) URL.revokeObjectURL(previous);
            return next;
          });
        } catch {
          /* a failed preview leaves the last good one on screen */
        }
      }
    } finally {
      busy.current = false;
    }
  }, []);

  // Anything still in flight belongs to the previous template, so its result
  // must not land on this one's canvas.
  useEffect(() => {
    return () => {
      generation.current += 1;
      queued.current = null;
    };
  }, [templateName]);

  useEffect(
    () => () => {
      generation.current += 1;
      if (current.current) URL.revokeObjectURL(current.current);
    },
    [],
  );

  const key = body === null ? null : JSON.stringify(body);

  useEffect(() => {
    if (key === null) return;
    const timer = setTimeout(() => {
      queued.current = { templateName, key, design };
      void pump();
    }, PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [templateName, key, design, pump]);

  return url;
}
