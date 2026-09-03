import { useCallback, useEffect, useState } from "react";
import { renderPreview } from "../api/calibrator";
import { Gallery } from "../components/Gallery";
import { QuadEditor } from "../components/QuadEditor";
import { DisplaceControls, ShadeControls } from "../components/RenderControls";
import type { BoundingBox, ColourMatrixTemplate } from "../types";

interface Props {
  templateName: string;
  config: ColourMatrixTemplate;
  colours: string[];
  onChange: (config: ColourMatrixTemplate) => void;
}

const PREVIEW_DEBOUNCE_MS = 200;

export function ColourMatrixEditor({ templateName, config, colours, onChange }: Props) {
  const [selectedColour, setSelectedColour] = useState<string | null>(null);
  // Derived rather than synced via effect+setState: falls back to the first
  // colour whenever the selection isn't (or is no longer) one of them --
  // covers both the initial mount and a colour list that changed underneath.
  const colour =
    selectedColour && colours.includes(selectedColour) ? selectedColour : (colours[0] ?? "");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!colour) return;
    const timer = setTimeout(() => {
      renderPreview(templateName, {
        colour,
        bounding_box: config.bounding_box,
        displace: config.displace,
        shade: config.shade,
      }).then((url) => {
        setPreviewUrl((previous) => {
          if (previous) URL.revokeObjectURL(previous);
          return url;
        });
      });
    }, PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [templateName, colour, config]);

  const handleBoxChange = useCallback(
    (_index: number, box: BoundingBox) => onChange({ ...config, bounding_box: box }),
    [config, onChange],
  );

  return (
    <>
      <main className="app__main">
        <div className="app__preview">
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
            />
          ) : (
            <p>Loading preview…</p>
          )}
        </div>

        <aside className="app__controls">
          <DisplaceControls
            value={config.displace}
            onChange={(displace) => onChange({ ...config, displace })}
          />
          <ShadeControls
            value={config.shade}
            onChange={(shade) => onChange({ ...config, shade })}
          />
        </aside>
      </main>
      <Gallery templateName={templateName} colours={colours} config={config} />
    </>
  );
}
