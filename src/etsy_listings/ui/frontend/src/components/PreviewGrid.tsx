import { useEffect, useRef, useState } from "react";
import { renderPreview } from "../api/calibrator";
import type { ColourMatrixTemplate } from "../types";

/**
 * Every colour in the set, rendered for real, as a grid (wireframe 2a's
 * "Preview all N" tab). This is the step where you stop adjusting and look at
 * the finished thing.
 *
 * Renders **sequentially**, not in parallel. The old gallery fired one request
 * per colour at once, which does not make the set arrive sooner -- the server
 * runs the real pipeline for each -- it only makes the *first* one arrive
 * later, and buries the progress count. One at a time means the grid fills in
 * visibly and the counter means something.
 */

interface Props {
  templateName: string;
  colours: string[];
  config: ColourMatrixTemplate;
  design: string;
  onApprove: () => void;
}

interface RunState {
  key: string;
  rendered: Record<string, string>;
  done: number;
  failed: number;
}

const EMPTY: Omit<RunState, "key"> = { rendered: {}, done: 0, failed: 0 };

export function PreviewGrid({ templateName, colours, config, design, onApprove }: Props) {
  // One state object stamped with the inputs it belongs to. Resetting on a
  // change is *derived* rather than done in an effect: clearing state from
  // inside an effect renders the stale values first and then throws them
  // away, which is both a wasted pass and the thing
  // `react-hooks/set-state-in-effect` exists to stop.
  const key = `${templateName}|${design}|${colours.join(",")}|${JSON.stringify(config)}`;
  const [state, setState] = useState<RunState>({ key, ...EMPTY });
  const view = state.key === key ? state : { key, ...EMPTY };
  const urlsRef = useRef<string[]>([]);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      for (const colour of colours) {
        if (cancelled) return;
        try {
          const url = await renderPreview(
            templateName,
            {
              colour,
              bounding_box: config.bounding_box,
              displace: config.displace,
              shade: config.shade,
            },
            design,
          );
          if (cancelled) {
            URL.revokeObjectURL(url);
            return;
          }
          urlsRef.current.push(url);
          setState((current) => {
            const base = current.key === key ? current : { key, ...EMPTY };
            return {
              key,
              rendered: { ...base.rendered, [colour]: url },
              done: base.done + 1,
              failed: base.failed,
            };
          });
        } catch {
          // One unreadable photo costs you that tile, not the whole tab.
          if (cancelled) return;
          setState((current) => {
            const base = current.key === key ? current : { key, ...EMPTY };
            return { ...base, key, failed: base.failed + 1 };
          });
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [key, templateName, colours, config, design]);

  // Revoked on unmount only: revoking per-render would pull the image out from
  // under a tile that is still on screen.
  useEffect(
    () => () => {
      for (const url of urlsRef.current) URL.revokeObjectURL(url);
      urlsRef.current = [];
    },
    [],
  );

  const { rendered, done, failed } = view;
  const complete = done + failed >= colours.length;

  return (
    <section className="preview-grid">
      <div className="preview-grid__head">
        <span className="preview-grid__count">{`${done} / ${colours.length}`}</span>
        {!complete && <span className="preview-grid__status">rendering the rest…</span>}
        {failed > 0 && (
          <span className="preview-grid__failed">
            {`${failed} colour${failed === 1 ? "" : "s"} failed to render`}
          </span>
        )}
        <button type="button" className="btn btn-primary" onClick={onApprove}>
          Approve &amp; mark calibrated
        </button>
      </div>

      <div className="preview-grid__tiles">
        {colours.map((colour) => (
          <figure key={colour} className="gallery__item preview-grid__tile">
            {rendered[colour] ? (
              <img src={rendered[colour]} alt={colour} />
            ) : (
              <div className="gallery__placeholder" />
            )}
            <figcaption>{colour}</figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}
