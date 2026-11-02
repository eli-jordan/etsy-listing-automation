import type { Issue } from "../../../src/types";
import { EditorFrame } from "./_EditorFrame";
import { artwork, foldedBox, limits, photos, stale } from "./_fixtures";
import { Foot, PositionChip, PositionSwitch } from "./_panes";
import { PositionStage } from "./_PositionStage";

export const meta = {
  title: "5 · Position outside the limits · v2",
  viewport: "laptop",
  description: "cc1717-folded was recalibrated, so this listing's stored box now sits 11% left of it. Plan refuses; the foot offers to pull it back in.",
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
      <Foot
        title="cc1717-folded · ivory"
        path="mockup-templates/cc1717-folded/ivory.png"
        note="Saved before the template's box moved"
        warn
        chip={<PositionChip pose={stale} invalid />}
        extra={
          <button type="button" className="btn-like btn-like--primary btn-sm" data-goto="template-positions-v2/02-adjusting">
            Fit within limits
          </button>
        }
        reset={() => {}}
        toggle={<PositionSwitch on />}
      />
    </>
  );
  return <EditorFrame pane={pane} issues={issues} />;
}
