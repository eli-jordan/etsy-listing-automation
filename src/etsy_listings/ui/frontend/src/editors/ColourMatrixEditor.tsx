import { useCallback, useMemo, useState } from "react";
import { PreviewGrid } from "../components/PreviewGrid";
import { PrintRealismPanel } from "../components/PrintRealismPanel";
import { QuadEditor } from "../components/QuadEditor";
import { TestDesignPicker } from "../components/TestDesignPicker";
import { usePreview } from "../hooks/usePreview";
import type { BoundingBox, ColourMatrixTemplate } from "../types";

interface Props {
  templateName: string;
  config: ColourMatrixTemplate;
  colours: string[];
  onChange: (config: ColourMatrixTemplate) => void;
  /** Which test artwork the preview renders with. A way of looking at the
   * template, not a property of it, so it lives above the config. */
  design: string;
  onDesignChange: (design: string) => void;
  /** Approving from the Preview-all tab saves; there is no separate stored
   * "approved" flag, because status is derived (see TemplateSummary.status). */
  onApprove: () => void;
}

export function ColourMatrixEditor({
  templateName,
  config,
  colours,
  onChange,
  design,
  onDesignChange,
  onApprove,
}: Props) {
  const [tab, setTab] = useState<"calibrate" | "preview">("calibrate");
  const [showOutlines, setShowOutlines] = useState(true);
  const [selectedColour, setSelectedColour] = useState<string | null>(null);
  // Derived rather than synced via effect+setState: falls back to the first
  // colour whenever the selection isn't (or is no longer) one of them --
  // covers both the initial mount and a colour list that changed underneath.
  const colour =
    selectedColour && colours.includes(selectedColour) ? selectedColour : (colours[0] ?? "");
  // No colour yet (an empty set, or a list that hasn't loaded) means there is
  // no photo to composite over, so the hook is told to hold off entirely.
  const previewUrl = usePreview(
    templateName,
    useMemo(
      () =>
        colour
          ? {
              colour,
              bounding_box: config.bounding_box,
              displace: config.displace,
              shade: config.shade,
            }
          : null,
      [colour, config.bounding_box, config.displace, config.shade],
    ),
    design,
  );

  const handleBoxChange = useCallback(
    (_index: number, box: BoundingBox) => onChange({ ...config, bounding_box: box }),
    [config, onChange],
  );

  return (
    <>
      <main className="app__main">
        <div className="app__preview">
          <div className="app__preview-bar">
            {/* 2a's Calibrate / Preview-all toggle. Two views of the same
                template: one to adjust in, one to judge in. */}
            <div className="seg" role="tablist" aria-label="View">
              <button
                type="button"
                role="tab"
                aria-selected={tab === "calibrate"}
                className={`seg-opt${tab === "calibrate" ? " seg-opt--on" : ""}`}
                onClick={() => setTab("calibrate")}
              >
                Calibrate
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === "preview"}
                className={`seg-opt${tab === "preview" ? " seg-opt--on" : ""}`}
                onClick={() => setTab("preview")}
              >
                {`Preview all ${colours.length}`}
              </button>
            </div>
            {tab === "calibrate" && (
              <label className="app__outline-toggle">
                <input
                  type="checkbox"
                  checked={showOutlines}
                  onChange={(e) => setShowOutlines(e.target.checked)}
                />
                show placement outline
              </label>
            )}
          </div>

          {tab === "preview" ? (
            <PreviewGrid
              templateName={templateName}
              colours={colours}
              config={config}
              design={design}
              onApprove={onApprove}
            />
          ) : (
            <>
              {colours.length > 1 && (
                <div className="app__filmstrip">
                  {colours.map((c) => (
                    <button
                      key={c}
                      className={
                        c === colour ? "filmstrip__item filmstrip__item--active" : "filmstrip__item"
                      }
                      onClick={() => setSelectedColour(c)}
                    >
                      {c}
                    </button>
                  ))}
                </div>
              )}
              {previewUrl ? (
                <QuadEditor
                  imageUrl={previewUrl}
                  boxes={[config.bounding_box]}
                  selectedIndex={0}
                  onSelect={() => {}}
                  onChangeBox={handleBoxChange}
                  outlines={showOutlines ? "all" : "none"}
                />
              ) : (
                <p>Loading preview…</p>
              )}
            </>
          )}
        </div>

        <aside className="app__controls">
          <TestDesignPicker value={design} onChange={onDesignChange} />
          <PrintRealismPanel
            displace={config.displace}
            shade={config.shade}
            onDisplaceChange={(displace) => onChange({ ...config, displace })}
            onShadeChange={(shade) => onChange({ ...config, shade })}
          />
        </aside>
      </main>
    </>
  );
}
