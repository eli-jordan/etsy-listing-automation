import { useEffect, useRef, useState } from "react";
import { renderPreview } from "../api/calibrator";
import type { ColourMatrixTemplate } from "../types";

interface Props {
  templateName: string;
  colours: string[];
  config: ColourMatrixTemplate;
}

const GALLERY_DEBOUNCE_MS = 800;

/**
 * Live preview of every colour in a `colour-matrix`-kind set at once, for
 * visual validation while calibrating. Deliberately slower than the main
 * `QuadEditor`'s live-drag preview (200ms) -- N parallel renders per edit
 * would hammer the server on every pointer-move frame otherwise. Reuses the
 * existing preview endpoint (one call per colour); no new API surface.
 */
export function Gallery({ templateName, colours, config }: Props) {
  const [thumbnails, setThumbnails] = useState<Record<string, string>>({});
  const urlsRef = useRef<string[]>([]);

  useEffect(() => {
    const timer = setTimeout(() => {
      Promise.all(
        colours.map(async (colour) => {
          const url = await renderPreview(templateName, {
            colour,
            bounding_box: config.bounding_box,
            displace: config.displace,
            shade: config.shade,
          });
          return [colour, url] as const;
        }),
      ).then((entries) => {
        urlsRef.current.forEach((url) => URL.revokeObjectURL(url));
        urlsRef.current = entries.map(([, url]) => url);
        setThumbnails(Object.fromEntries(entries));
      });
    }, GALLERY_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [templateName, colours, config]);

  useEffect(() => () => urlsRef.current.forEach((url) => URL.revokeObjectURL(url)), []);

  if (colours.length <= 1) return null;

  return (
    <div className="gallery" aria-label="All colours">
      {colours.map((colour) => (
        <figure key={colour} className="gallery__item">
          {thumbnails[colour] ? (
            <img src={thumbnails[colour]} alt={colour} />
          ) : (
            <div className="gallery__placeholder" aria-label={`${colour} loading`} />
          )}
          <figcaption>{colour}</figcaption>
        </figure>
      ))}
    </div>
  );
}
