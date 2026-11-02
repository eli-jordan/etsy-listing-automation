import { useState, type ReactNode } from "react";
import { artwork, foldedBox, identity, limits, photos } from "./_fixtures";
import { PositionGlyph } from "./_EditorFrame";
import { deg, isIdentity, pct, type Pose } from "./_geometry";
import { PositionStage } from "./_PositionStage";
import { Readout } from "./_Readout";

const SIZE = { w: 480, h: 480 };
const TITLE = "cc1717-folded · ivory";
const PATH = "mockup-templates/cc1717-folded/ivory.png";

/** "92% · up 6%" -- the pose in the words the chip uses. */
export function summary(p: Pose): string {
  const parts = [pct(p.scale)];
  if (p.dy) parts.push(`${p.dy < 0 ? "up" : "down"} ${pct(Math.abs(p.dy))}`);
  if (p.dx) parts.push(`${p.dx < 0 ? "left" : "right"} ${pct(Math.abs(p.dx))}`);
  if (p.rotation) parts.push(deg(p.rotation));
  return parts.join(" · ");
}

function Meta({ extra }: { extra?: ReactNode }) {
  return (
    <span className="preview-meta">
      <span className="preview-meta__title">{TITLE}</span>
      <span className="preview-meta__path">{PATH}</span>
      {extra}
    </span>
  );
}

/** Viewing an entry: the composite at the listing's position, and the way in. */
export function ViewPane({ pose }: { pose: Pose }) {
  return (
    <>
      <div className="preview-stage preview-stage--large">
        <PositionStage photo={photos.ivory} size={SIZE} artwork={artwork} layers={[{ id: "main", box: foldedBox, pose }]} limits={limits} />
      </div>
      <div className="preview-foot tp-foot">
        <Meta />
        {isIdentity(pose) ? (
          <span className="tp-chip tp-chip--muted">Template position</span>
        ) : (
          <span className="tp-chip" title="This listing positions the design on cc1717-folded">
            <PositionGlyph /> Custom · {summary(pose)}
          </span>
        )}
        <span className="preview-actions">
          <button type="button" className="btn-like btn-like--ghost btn-sm" data-goto="template-positions-v1/adjust/a-foot-bar">
            <PositionGlyph /> Adjust position
          </button>
          <button type="button" className="btn-like btn-like--ghost btn-sm">
            Remove from listing
          </button>
        </span>
      </div>
    </>
  );
}

const SCOPE = "Applies to all 4 cc1717-folded colours in this listing";

/** Variant A: the foot becomes the position bar. */
export function BarPane({ initial }: { initial: Pose }) {
  const [pose, setPose] = useState(initial);
  return (
    <>
      <div className="preview-stage preview-stage--large tp-stage-box--editing">
        <PositionStage
          photo={photos.ivory}
          size={SIZE}
          artwork={artwork}
          layers={[{ id: "main", box: foldedBox, pose, label: "Design" }]}
          editing="main"
          ghost
          limits={limits}
          onChange={(_, p) => setPose(p)}
        />
      </div>
      <div className="tp-bar" role="group" aria-label="Design position">
        <div className="tp-bar__lede">
          <strong>Position on cc1717-folded</strong>
          <span>{SCOPE}. Dashed outline: the template's box.</span>
        </div>
        <Readout pose={pose} limits={limits} layout="row" />
        <div className="tp-bar__actions">
          <button type="button" className="btn-like btn-like--ghost btn-sm" disabled={isIdentity(pose)} onClick={() => setPose(identity)}>
            Reset to template
          </button>
          <button type="button" className="btn-like btn-like--ghost btn-sm" data-goto="template-positions-v1/01-selected">
            Cancel
          </button>
          <button type="button" className="btn-like btn-like--primary btn-sm" data-goto="template-positions-v1/01-selected">
            Done
          </button>
        </div>
      </div>
    </>
  );
}

/** Variant B: an inspector card pinned to the stage; the foot stays put. */
export function InspectorPane({ initial }: { initial: Pose }) {
  const [pose, setPose] = useState(initial);
  return (
    <>
      <div className="preview-stage preview-stage--large">
        <div className="tp-stage-wrap">
          <PositionStage
            photo={photos.ivory}
            size={SIZE}
            artwork={artwork}
            layers={[{ id: "main", box: foldedBox, pose, label: "Design" }]}
            editing="main"
            ghost
            limits={limits}
            onChange={(_, p) => setPose(p)}
          />
          <section className="tp-inspector" aria-label="Design position">
            <div className="tp-inspector__title">
              Position
              <button type="button" className="btn-like btn-like--ghost btn-sm" disabled={isIdentity(pose)} onClick={() => setPose(identity)}>
                Reset
              </button>
            </div>
            <Readout pose={pose} limits={limits} layout="column" />
            <div className="tp-inspector__actions">
              <button type="button" className="btn-like btn-like--ghost btn-sm" data-goto="template-positions-v1/01-selected">
                Cancel
              </button>
              <button type="button" className="btn-like btn-like--primary btn-sm" data-goto="template-positions-v1/01-selected">
                Done
              </button>
            </div>
          </section>
        </div>
      </div>
      <div className="preview-foot tp-foot">
        <Meta extra={<span className="preview-meta__note preview-meta__note--info">{SCOPE}</span>} />
        <span className="tp-chip">
          <PositionGlyph /> Editing position
        </span>
      </div>
    </>
  );
}
