import { useCallback, useEffect, useState } from "react";
import { renderPreview } from "../api/calibrator";
import { PlacementsPanel } from "../components/PlacementsPanel";
import { PrintRealismPanel } from "../components/PrintRealismPanel";
import { QuadEditor } from "../components/QuadEditor";
import { TestDesignPicker } from "../components/TestDesignPicker";
import type { BoundingBox, MultipleTemplate, Placement } from "../types";

interface Props {
  templateName: string;
  config: MultipleTemplate;
  onChange: (config: MultipleTemplate) => void;
  design: string;
  onDesignChange: (design: string) => void;
}

const PREVIEW_DEBOUNCE_MS = 200;

/**
 * The one output *is* the live composite of every placement, so there's no
 * separate gallery need here (unlike colour-matrix kind) -- the main preview
 * already shows everything at once.
 */
export function MultipleEditor({
  templateName,
  config,
  onChange,
  design,
  onDesignChange,
}: Props) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      renderPreview(
        templateName,
        {
          placements: config.placements,
          displace: config.displace,
          shade: config.shade,
        },
        design,
      ).then((url) => {
        setPreviewUrl((previous) => {
          if (previous) URL.revokeObjectURL(previous);
          return url;
        });
      });
    }, PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [templateName, config, design]);

  const handleBoxChange = useCallback(
    (index: number, box: BoundingBox) =>
      onChange({
        ...config,
        placements: config.placements.map((p, i) =>
          i === index ? { ...p, bounding_box: box } : p,
        ),
      }),
    [config, onChange],
  );

  const handlePlacementsChange = useCallback(
    (placements: Placement[]) => onChange({ ...config, placements }),
    [config, onChange],
  );

  const clampedIndex = Math.min(selectedIndex, Math.max(config.placements.length - 1, 0));

  return (
    <main className="app__main">
      <div className="app__preview">
        {previewUrl ? (
          <QuadEditor
            imageUrl={previewUrl}
            boxes={config.placements.map((p) => p.bounding_box)}
            selectedIndex={clampedIndex}
            onSelect={setSelectedIndex}
            onChangeBox={handleBoxChange}
          />
        ) : (
          <p>Loading preview…</p>
        )}
      </div>

      <aside className="app__controls">
        {/* `colour_coverage` has no home in wireframe 2a and is, for now,
            editable only by hand in template.yaml. Recorded as a debt in
            docs/implementation-plan.md -- it belongs in the Advanced
            disclosure when it comes back. */}
        <TestDesignPicker value={design} onChange={onDesignChange} />
        <PrintRealismPanel
          displace={config.displace}
          shade={config.shade}
          onDisplaceChange={(displace) => onChange({ ...config, displace })}
          onShadeChange={(shade) => onChange({ ...config, shade })}
        />
        <PlacementsPanel
          placements={config.placements}
          selectedIndex={clampedIndex}
          onSelect={setSelectedIndex}
          onChange={handlePlacementsChange}
        />
      </aside>
    </main>
  );
}
