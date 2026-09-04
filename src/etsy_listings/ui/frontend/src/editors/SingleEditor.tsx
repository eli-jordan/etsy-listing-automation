import { useCallback, useEffect, useState } from "react";
import { renderPreview } from "../api/calibrator";
import { PrintRealismPanel } from "../components/PrintRealismPanel";
import { QuadEditor } from "../components/QuadEditor";
import { TestDesignPicker } from "../components/TestDesignPicker";
import type { BoundingBox, SingleTemplate } from "../types";

interface Props {
  templateName: string;
  config: SingleTemplate;
  onChange: (config: SingleTemplate) => void;
  design: string;
  onDesignChange: (design: string) => void;
}

const PREVIEW_DEBOUNCE_MS = 200;

/** The simplest of the three: one box, sliders, no filmstrip, no placements
 * panel -- one photo, one garment, nothing to disambiguate. */
export function SingleEditor({
  templateName,
  config,
  onChange,
  design,
  onDesignChange,
}: Props) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      renderPreview(
        templateName,
        {
          bounding_box: config.bounding_box,
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
    (_index: number, box: BoundingBox) => onChange({ ...config, bounding_box: box }),
    [config, onChange],
  );

  return (
    <main className="app__main">
      <div className="app__preview">
        {previewUrl ? (
          <QuadEditor
            imageUrl={previewUrl}
            boxes={[config.bounding_box]}
            selectedIndex={0}
            onSelect={() => {}}
            onChangeBox={handleBoxChange}
          />
        ) : (
          <p>Loading preview…</p>
        )}
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
