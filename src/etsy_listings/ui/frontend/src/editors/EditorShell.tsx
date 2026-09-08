import { type ReactNode, useState } from "react";
import { PreviewPanel, type PreviewJob } from "../components/PreviewPanel";
import { PrintRealismPanel } from "../components/PrintRealismPanel";
import { QuadEditor } from "../components/QuadEditor";
import { TestDesignPicker } from "../components/TestDesignPicker";
import { ViewTabs, type View } from "../components/ViewTabs";
import type { BoundingBox, DisplaceConfig, ShadeConfig } from "../types";

/** The parts of a template.yaml every kind has, and this shell edits directly.
 * Everything else about a config is the kind's own business. */
export interface RealismConfig {
  displace: DisplaceConfig;
  shade: ShadeConfig;
}

/** What a canvas is handed once the shell knows there is something to draw. */
export interface CanvasContext {
  imageUrl: string;
  space: [number, number];
  showOutlines: boolean;
}

interface Props<T extends RealismConfig> {
  templateName: string;
  config: T;
  onChange: (config: T) => void;
  design: string;
  onDesignChange: (design: string) => void;
  /** The photo's true pixel size, or `null` when there is no readable photo.
   * With no space there is nothing to calibrate against, so the canvas is
   * replaced by the loading line rather than drawn in the wrong coordinates.
   * See `QuadEditor`'s `space`. */
  space: [number, number] | null;
  previewUrl: string | null;
  jobs: PreviewJob[];
  onApprove?: () => void;
  /** What the outline checkbox says. One box or twelve changes the wording,
   * not the control. */
  outlineLabel?: string;
  /** The calibration canvas. A function, not a node, because everything it
   * needs is decided here: the toggle that says whether outlines are drawn
   * lives in this bar, and the image and the space it is in are only known to
   * exist inside the guard below -- handing them over is what lets a kind's
   * canvas take them as plain non-null values. */
  canvas: (ctx: CanvasContext) => ReactNode;
  /** Extra controls in the view bar, shown on the Calibrate tab only --
   * a colour-matrix set's colour selector is the only one so far. */
  barExtras?: ReactNode;
  /** Extra controls at the top of the inspector, above the design picker. */
  controls?: ReactNode;
  /** Shown under the canvas on the Calibrate tab -- a chart's "boxes with no
   * colour" warning. */
  footer?: ReactNode;
}

/**
 * The workbench every template kind is edited in: a view bar, a canvas, a
 * full-size preview panel, and an inspector.
 *
 * This was written out three times, once per kind, down to the class names and
 * the `previewUrl && space ? canvas : "Loading preview…"` gate. The kinds
 * genuinely differ in what goes *on* the canvas -- one box, one box seen in
 * twelve colours, or many boxes with captions -- and in nothing else. Three
 * copies of the frame meant a change to the chrome either landed three times
 * or, more often, once: the outline toggle reached `single` and
 * `colour-matrix` and not `multiple` for exactly that reason.
 *
 * So the kind supplies its canvas and its extra controls; the shell owns
 * which tab is showing, whether outlines are drawn, and the layout around
 * them.
 */
export function EditorShell<T extends RealismConfig>({
  templateName,
  config,
  onChange,
  design,
  onDesignChange,
  space,
  previewUrl,
  jobs,
  onApprove,
  outlineLabel = "show placement outline",
  canvas,
  barExtras,
  controls,
  footer,
}: Props<T>) {
  const [tab, setTab] = useState<View>("calibrate");
  const [showOutlines, setShowOutlines] = useState(true);
  const calibrating = tab === "calibrate";

  return (
    <main className="app__main">
      <div className="app__preview">
        <div className="app__preview-bar">
          {/* Two views of the same template: one to adjust in, one to judge
              in. Shared by all three kinds -- see ViewTabs. */}
          <ViewTabs value={tab} onChange={setTab} />
          {calibrating && barExtras}
          {calibrating && (
            <label className="app__outline-toggle">
              <input
                type="checkbox"
                checked={showOutlines}
                onChange={(e) => setShowOutlines(e.target.checked)}
              />
              {outlineLabel}
            </label>
          )}
        </div>

        {calibrating &&
          (previewUrl && space ? (
            canvas({ imageUrl: previewUrl, space, showOutlines })
          ) : (
            <p className="app__loading">Loading preview…</p>
          ))}

        {/* Mounted either way, so flicking back to Calibrate and returning
            does not throw away renders that cost real seconds. */}
        <PreviewPanel
          templateName={templateName}
          jobs={jobs}
          design={design}
          active={tab === "preview"}
          // Spread rather than passed: under `exactOptionalPropertyTypes` an
          // absent optional prop and one explicitly set to `undefined` are
          // different types, and only `colour-matrix` has an approve action.
          {...(onApprove ? { onApprove } : {})}
        />
        {calibrating && footer}
      </div>

      <aside className="app__controls">
        {controls}
        <TestDesignPicker value={design} onChange={onDesignChange} />
        <PrintRealismPanel
          displace={config.displace}
          shade={config.shade}
          onDisplaceChange={(displace) => onChange({ ...config, displace })}
          onShadeChange={(shade) => onChange({ ...config, shade })}
        />
      </aside>
    </main>
  );
}

/**
 * The canvas for a kind with exactly one box: `colour-matrix` and `single`.
 *
 * They differ in which photo is underneath -- twelve colours of one garment,
 * or one scene -- and the geometry is identical, which is why one box is
 * always selected and selection is a no-op.
 */
export function OneBoxCanvas({
  imageUrl,
  space,
  box,
  onChange,
  showOutlines,
}: {
  imageUrl: string;
  space: [number, number];
  box: BoundingBox;
  onChange: (box: BoundingBox) => void;
  showOutlines: boolean;
}) {
  return (
    <QuadEditor
      imageUrl={imageUrl}
      space={space}
      boxes={[box]}
      selectedIndex={0}
      onSelect={() => {}}
      onChangeBox={(_index, next) => onChange(next)}
      outlines={showOutlines ? "all" : "none"}
    />
  );
}
