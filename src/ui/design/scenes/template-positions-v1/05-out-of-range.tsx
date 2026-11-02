import type { Issue } from "../../../src/types";
import { EditorFrame } from "./_EditorFrame";
import { artwork, foldedBox, limits, photos, stale } from "./_fixtures";
import { PositionStage } from "./_PositionStage";
import { Readout } from "./_Readout";

export const meta = {
  title: "5 · Position outside the limits · v1",
  viewport: "laptop",
  description: "cc1717-folded was recalibrated, so this listing's stored box now sits 11% left of it. Plan refuses; the editor offers to pull it back in.",
};

const issues = [
  {
    message:
      "The design on cc1717-folded sits 11% left of the template's box; the limit is 10%. The box moved when cc1717-folded was recalibrated",
    severity: "block",
    tab: "images",
    where: "Listing Images",
  },
] as Issue[];

export default function Frame() {
  const pane = (
    <>
      <div className="preview-stage preview-stage--large tp-stage-box--editing">
        <PositionStage
          photo={photos.ivory}
          size={{ w: 480, h: 480 }}
          artwork={artwork}
          layers={[{ id: "main", box: foldedBox, pose: stale, label: "Design" }]}
          editing="main"
          ghost
          invalid="main"
          limits={{ ...limits, offset: 1 }}
        />
      </div>
      <div className="tp-bar" role="group" aria-label="Design position">
        <div className="tp-bar__lede">
          <strong>Position on cc1717-folded</strong>
          <span className="tp-chip tp-chip--danger">Blocks deploy</span>
          <span>Saved before the template box moved. Pull it back in, or start again from the template.</span>
        </div>
        <Readout pose={stale} limits={limits} layout="row" />
        <div className="tp-bar__actions">
          <button type="button" className="btn-like btn-like--ghost btn-sm" data-goto="template-positions-v1/01-selected">
            Reset to template
          </button>
          <button type="button" className="btn-like btn-like--primary btn-sm" data-goto="template-positions-v1/adjust/a-foot-bar">
            Fit within limits
          </button>
        </div>
      </div>
    </>
  );
  return <EditorFrame pane={pane} issues={issues} />;
}
