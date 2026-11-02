import type { Issue } from "../../../src/types";
import { EditorFrame } from "./_EditorFrame";
import { artwork, foldedBox, limits, photos, stale } from "./_fixtures";
import { Foot, PositionSwitch } from "./_panes";
import { PositionStage } from "./_PositionStage";

export const meta = {
  title: "4 · Position outside the limits",
  viewport: "laptop",
  description: "Second entry point: cc1717-folded was recalibrated and this listing's box now falls outside the limits. Fit within limits or Reset to template both resolve it.",
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
      <div className="preview-stage preview-stage--large">
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
      <div className="preview-foot tp-foot">
        <span className="preview-meta">
          <span className="preview-meta__title">cc1717-folded · ivory</span>
          <span className="preview-meta__path">mockup-templates/cc1717-folded/ivory.png</span>
          <span className="tp-note tp-note--warn">Outside the limits since the template's box moved</span>
        </span>
        <span className="tp-controls">
          <button type="button" className="btn-like btn-like--primary btn-sm" data-goto="template-positions/02-adjusting">
            Fit within limits
          </button>
          <button type="button" className="tp-link" data-goto="template-positions/01-selected">
            Reset to template
          </button>
          <PositionSwitch on goto="template-positions/01-selected" />
        </span>
      </div>
    </>
  );
  return <EditorFrame pane={pane} issues={issues} />;
}
