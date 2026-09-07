import { useCallback, useMemo, useState } from "react";
import { PreviewPanel, type PreviewJob } from "../components/PreviewPanel";
import { PrintRealismPanel } from "../components/PrintRealismPanel";
import { QuadEditor } from "../components/QuadEditor";
import { TestDesignPicker } from "../components/TestDesignPicker";
import { ViewTabs, type View } from "../components/ViewTabs";
import { usePreview } from "../hooks/usePreview";
import type { BoundingBox, ColourMatrixTemplate } from "../types";

interface Props {
  templateName: string;
  config: ColourMatrixTemplate;
  colours: string[];
  /** The photo's true pixel size -- the space the boxes are in. See
   * `QuadEditor`'s `space`. */
  space: [number, number] | null;
  onChange: (config: ColourMatrixTemplate) => void;
  /** Which test artwork the preview renders with. A way of looking at the
   * template, not a property of it, so it lives above the config. */
  design: string;
  onDesignChange: (design: string) => void;
  /** Approving from the Preview tab saves; there is no separate stored
   * "approved" flag, because status is derived (see TemplateSummary.status). */
  onApprove: () => void;
}

export function ColourMatrixEditor({
  templateName,
  config,
  colours,
  space,
  onChange,
  design,
  onDesignChange,
  onApprove,
}: Props) {
  const [tab, setTab] = useState<View>("calibrate");
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

  // One full-size render per colour in the set -- the whole point of this kind
  // is that one box has to work in all of them.
  const jobs: PreviewJob[] = useMemo(
    () =>
      colours.map((c) => ({
        id: c,
        label: c,
        body: {
          colour: c,
          bounding_box: config.bounding_box,
          displace: config.displace,
          shade: config.shade,
        },
      })),
    [colours, config.bounding_box, config.displace, config.shade],
  );

  const handleBoxChange = useCallback(
    (_index: number, box: BoundingBox) => onChange({ ...config, bounding_box: box }),
    [config, onChange],
  );

  return (
    <main className="app__main">
      <div className="app__preview">
        <div className="app__preview-bar">
          {/* Two views of the same template: one to adjust in, one to judge
              in. Shared with the other two kinds -- see ViewTabs. */}
          <ViewTabs value={tab} onChange={setTab} />
          {/* Which colour the canvas is showing. A row of pills used to sit
              between the tabs and the photo, pushing the thing being
              calibrated down the page and growing with the set -- a
              twelve-colour garment wrapped onto two lines. It is a choice of
              one from a list, which is what a select is for, and it belongs
              beside the other control that says what you are looking at.

              Only when there is a choice to make: a one-colour set has none,
              and the Preview tab renders every colour regardless. */}
          {tab === "calibrate" && colours.length > 1 && (
            <label className="app__bar-field">
              <span>Colour</span>
              <select value={colour} onChange={(e) => setSelectedColour(e.target.value)}>
                {colours.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
          )}
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

        {tab === "calibrate" &&
          (previewUrl && space ? (
            <QuadEditor
              imageUrl={previewUrl}
              space={space}
              boxes={[config.bounding_box]}
              selectedIndex={0}
              onSelect={() => {}}
              onChangeBox={handleBoxChange}
              outlines={showOutlines ? "all" : "none"}
            />
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
          onApprove={onApprove}
        />
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
  );
}
