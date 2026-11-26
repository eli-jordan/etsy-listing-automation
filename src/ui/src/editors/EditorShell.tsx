import { type ReactNode, useState } from "react";
import { BoxToggle } from "../components/BoxToggle";
import { PreviewPanel, type PreviewJob } from "../components/PreviewPanel";
import { PrintRealismPanel } from "../components/PrintRealismPanel";
import { QuadEditor } from "../components/QuadEditor";
import { TestDesignPicker } from "../components/TestDesignPicker";
import { ViewTabs, type View } from "../components/ViewTabs";
import type { BoundingBox, PhotoSpace, PhotoWarpRenderer } from "../types";

export interface PhotoWarpConfig {
  renderer: PhotoWarpRenderer;
}

export interface CanvasContext {
  imageUrl: string;
  space: PhotoSpace;
  showOutlines: boolean;
}

interface Props<T extends PhotoWarpConfig> {
  rendererControls?: ReactNode;
  templateName: string;
  config: T;
  onChange: (config: T) => void;
  design: string;
  onDesignChange: (design: string) => void;
  space: PhotoSpace | null;
  previewUrl: string | null;
  jobs: PreviewJob[];
  onApprove?: () => void;
  outlineLabel?: string;
  canvas: (ctx: CanvasContext) => ReactNode;
  barExtras?: ReactNode;
  footer?: ReactNode;
}

export function EditorShell<T extends PhotoWarpConfig>({
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
  space: PhotoSpace;
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
