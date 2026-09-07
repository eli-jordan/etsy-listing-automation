import { useCallback, useMemo, useState } from "react";
import { PreviewPanel, type PreviewJob } from "../components/PreviewPanel";
import { PrintRealismPanel } from "../components/PrintRealismPanel";
import { QuadEditor } from "../components/QuadEditor";
import { TestDesignPicker } from "../components/TestDesignPicker";
import { ViewTabs, type View } from "../components/ViewTabs";
import { usePreview } from "../hooks/usePreview";
import type { BoundingBox, SingleTemplate } from "../types";

interface Props {
  templateName: string;
  config: SingleTemplate;
  /** The photo's true pixel size -- the space the box is in. See
   * `QuadEditor`'s `space`. */
  space: [number, number] | null;
  onChange: (config: SingleTemplate) => void;
  design: string;
  onDesignChange: (design: string) => void;
}

/** The simplest of the three: one box, sliders, no filmstrip, no placements
 * panel -- one photo, one garment, nothing to disambiguate.
 *
 * It carries the same "show placement outline" toggle as a colour set, for
 * the same reason: the box and its handles sit on top of the very artwork you
 * are judging, and with one always-selected box there was previously no way
 * to get them out of the way. */
export function SingleEditor({
  templateName,
  config,
  space,
  onChange,
  design,
  onDesignChange,
}: Props) {
  const [tab, setTab] = useState<View>("calibrate");
  const [showOutlines, setShowOutlines] = useState(true);

  const previewUrl = usePreview(
    templateName,
    useMemo(
      () => ({
        bounding_box: config.bounding_box,
        displace: config.displace,
        shade: config.shade,
      }),
      [config.bounding_box, config.displace, config.shade],
    ),
    design,
  );

  // One output, so one job -- but the same on-demand full-size render as a
  // colour set gets, because the reason for it (the canvas draws a downscale)
  // has nothing to do with how many photos a kind has.
  const jobs: PreviewJob[] = useMemo(
    () => [
      {
        id: templateName,
        label: config.colour ?? templateName,
        body: {
          bounding_box: config.bounding_box,
          displace: config.displace,
          shade: config.shade,
        },
      },
    ],
    [templateName, config.colour, config.bounding_box, config.displace, config.shade],
  );

  const handleBoxChange = useCallback(
    (_index: number, box: BoundingBox) => onChange({ ...config, bounding_box: box }),
    [config, onChange],
  );

  return (
    <main className="app__main">
      <div className="app__preview">
        <div className="app__preview-bar">
          <ViewTabs value={tab} onChange={setTab} />
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
        <PreviewPanel
          templateName={templateName}
          jobs={jobs}
          design={design}
          active={tab === "preview"}
        />
      </div>

      <aside className="app__controls">
        <label>
          Garment colour (optional)
          <input
            value={config.colour ?? ""}
            onChange={(e) => onChange({ ...config, colour: e.target.value || null })}
            placeholder="for artwork resolution, if relevant"
          />
        </label>
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
