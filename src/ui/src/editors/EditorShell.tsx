import { type ReactNode, useState } from "react";
import { BoxToggle } from "../components/BoxToggle";
import { PreviewPanel, type PreviewJob } from "../components/PreviewPanel";
import { PrintRealismPanel } from "../components/PrintRealismPanel";
import { QuadEditor } from "../components/QuadEditor";
import { TestDesignPicker } from "../components/TestDesignPicker";
import { ViewTabs, type View } from "../components/ViewTabs";
import type { BoundingBox, PhotoWarpRenderer } from "../types";

/** The parts of a template.yaml every kind has, and this shell edits directly.
 * Everything else about a config is the kind's own business. */
export interface RealismConfig {
  renderer: PhotoWarpRenderer;
}

export interface CanvasContext {
  imageUrl: string;
  space: [number, number];
  showOutlines: boolean;
}

interface Props<T extends RealismConfig> {
  rendererControls?: ReactNode;
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
  outlineLabel?: string;
  canvas: (ctx: CanvasContext) => ReactNode;
  barExtras?: ReactNode;
  controls?: ReactNode;
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
  rendererControls,
  templateName,
  config,
  onChange,
  design,
  onDesignChange,
  space,
  previewUrl,
  jobs,
  onApprove,
  outlineLabel = "Show design box",
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
          <ViewTabs value={tab} onChange={setTab} />
          <TestDesignPicker compact value={design} onChange={onDesignChange} />
          {calibrating && barExtras}
          {calibrating && (
            <div className="app__outline-toggle">
              <BoxToggle checked={showOutlines} onChange={setShowOutlines} label={outlineLabel} />
            </div>
          )}
        </div>

        {calibrating &&
          (previewUrl && space ? (
            canvas({ imageUrl: previewUrl, space, showOutlines })
          ) : (
            <p className="app__loading">Loading preview…</p>
          ))}

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
        {rendererControls}
        <PrintRealismPanel
          displace={config.renderer.config.displace}
          shade={config.renderer.config.shade}
          onDisplaceChange={(displace) =>
            onChange({
              ...config,
              renderer: { ...config.renderer, config: { ...config.renderer.config, displace } },
            })
          }
          onShadeChange={(shade) =>
            onChange({
              ...config,
              renderer: { ...config.renderer, config: { ...config.renderer.config, shade } },
            })
          }
        />
      </aside>
    </main>
  );
}

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
