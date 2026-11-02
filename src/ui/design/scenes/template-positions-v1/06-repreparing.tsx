import { EditorFrame } from "./_EditorFrame";
import { artwork, foldedBox, limits, photos, tuned } from "./_fixtures";
import { summary } from "./_panes";
import { PositionGlyph } from "./_EditorFrame";
import { PositionStage } from "./_PositionStage";

export const meta = {
  title: "6 · Marigold template re-preparing · v1",
  viewport: "laptop",
  description: "The position limits changed, so cc1717-folded is re-preparing in the background. The saved position stands; its preview and deploy wait.",
};

export default function Frame() {
  const pane = (
    <>
      <div className="preview-stage preview-stage--large">
        <div className="tp-stage-wrap">
          <div className="tp-stage-wrap tp-stage--muted" aria-hidden="true">
            <PositionStage photo={photos.ivory} size={{ w: 480, h: 480 }} artwork={artwork} layers={[{ id: "main", box: foldedBox, pose: tuned }]} limits={limits} />
          </div>
          <div className="tp-stage-note" role="status">
            <p>
              <strong>cc1717-folded is re-preparing</strong> because the position limits changed. This preview and
              deploying this listing wait until it finishes.
            </p>
            <span className="tp-progress" aria-label="42% done">
              <span style={{ width: "42%" }} />
            </span>
            <span>42% · about 6 min left</span>
          </div>
        </div>
      </div>
      <div className="preview-foot tp-foot">
        <span className="preview-meta">
          <span className="preview-meta__title">cc1717-folded · ivory</span>
          <span className="preview-meta__path">Marigold · re-preparing 1 of 3 templates</span>
        </span>
        <span className="tp-chip">
          <PositionGlyph /> Custom · {summary(tuned)}
        </span>
        <span className="preview-actions">
          <button type="button" className="btn-like btn-like--ghost btn-sm" disabled title="Available once cc1717-folded finishes preparing — there's no preview to judge by until then">
            <PositionGlyph /> Adjust position
          </button>
        </span>
      </div>
    </>
  );
  return <EditorFrame pane={pane} />;
}
