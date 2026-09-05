import { useCallback, useMemo, useState } from "react";
import { PlacementsPanel } from "../components/PlacementsPanel";
import { PrintRealismPanel } from "../components/PrintRealismPanel";
import { QuadEditor } from "../components/QuadEditor";
import { TestDesignPicker } from "../components/TestDesignPicker";
import { usePreview } from "../hooks/usePreview";
import type { BoundingBox, MultipleTemplate, Placement } from "../types";

interface Props {
  templateName: string;
  config: MultipleTemplate;
  onChange: (config: MultipleTemplate) => void;
  design: string;
  onDesignChange: (design: string) => void;
  /** Colours already used across the workspace, offered as suggestions when
   * assigning one to a box. Suggestions only: a chart's colours are whatever
   * the listing sells, which the calibrator does not know. */
  knownColours: string[];
}

/** Where the very first box lands when the photo has none. Middle-ish and
 * comfortably grabbable; it is meant to be dragged, not to be right. */
const CENTRED_BOX: BoundingBox = [
  { x: 200, y: 150 },
  { x: 400, y: 150 },
  { x: 400, y: 350 },
  { x: 200, y: 350 },
];

function boxExtent(box: BoundingBox): string {
  const xs = box.map((p) => p.x);
  const ys = box.map((p) => p.y);
  const width = Math.round(Math.max(...xs) - Math.min(...xs));
  const height = Math.round(Math.max(...ys) - Math.min(...ys));
  return `${width} × ${height}`;
}

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
  knownColours,
}: Props) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [showOutlines, setShowOutlines] = useState(true);

  const previewUrl = usePreview(
    templateName,
    useMemo(
      () => ({
        placements: config.placements,
        displace: config.displace,
        shade: config.shade,
      }),
      [config.placements, config.displace, config.shade],
    ),
    design,
  );

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
  const selected = config.placements[clampedIndex];

  /** The box-editing operations live on the panel, and the canvas reaches
   * them through here -- one implementation, whether you used the right-click
   * menu, the Delete key or the button. */
  const mutate = useCallback(
    (fn: (placements: Placement[]) => { placements: Placement[]; select: number }) => {
      const result = fn(config.placements);
      onChange({ ...config, placements: result.placements });
      setSelectedIndex(result.select);
    },
    [config, onChange],
  );

  const addBox = useCallback(
    () =>
      mutate((placements) => {
        const source = placements[clampedIndex] ?? placements[placements.length - 1];
        // 2a: lands centred and selected -- no drawing mode, and every corner
        // stays draggable afterwards. Offset from the last box when there is
        // one, so a new box is never hidden exactly under its source.
        const bounding_box = source
          ? (source.bounding_box.map((p) => ({
              x: p.x + (Math.max(...source.bounding_box.map((q) => q.x)) -
                Math.min(...source.bounding_box.map((q) => q.x))),
              y: p.y,
            })) as BoundingBox)
          : CENTRED_BOX;
        return {
          placements: [...placements, { colour: "", bounding_box, artwork: null }],
          select: placements.length,
        };
      }),
    [mutate, clampedIndex],
  );

  const deleteSelected = useCallback(
    () =>
      mutate((placements) => ({
        placements: placements.filter((_, i) => i !== clampedIndex),
        select: Math.max(0, clampedIndex - 1),
      })),
    [mutate, clampedIndex],
  );

  const duplicateSelected = useCallback(
    () =>
      mutate((placements) => {
        const source = placements[clampedIndex];
        if (!source) return { placements, select: clampedIndex };
        const width =
          Math.max(...source.bounding_box.map((p) => p.x)) -
          Math.min(...source.bounding_box.map((p) => p.x));
        const copy: Placement = {
          ...source,
          bounding_box: source.bounding_box.map((p) => ({ x: p.x + width, y: p.y })) as BoundingBox,
        };
        const next = [...placements];
        next.splice(clampedIndex + 1, 0, copy);
        return { placements: next, select: clampedIndex + 1 };
      }),
    [mutate, clampedIndex],
  );

  const bringToFront = useCallback(
    () =>
      mutate((placements) => {
        const source = placements[clampedIndex];
        if (!source) return { placements, select: clampedIndex };
        const next = placements.filter((_, i) => i !== clampedIndex);
        next.push(source);
        return { placements: next, select: next.length - 1 };
      }),
    [mutate, clampedIndex],
  );

  return (
    <main className="app__main">
      <div className="app__preview">
        <div className="app__preview-bar">
          <label className="app__outline-toggle">
            <input
              type="checkbox"
              checked={showOutlines}
              onChange={(e) => setShowOutlines(e.target.checked)}
            />
            show all outlines
          </label>
        </div>
        {previewUrl ? (
          config.placements.length === 0 ? (
            <div className="quad-editor__empty">
              <p>No bounding boxes on this photo</p>
              <button type="button" className="btn btn-primary" onClick={addBox}>
                + Add box
              </button>
              <p className="quad-editor__empty-hint">first box lands ready to drag</p>
            </div>
          ) : (
            <QuadEditor
              imageUrl={previewUrl}
              boxes={config.placements.map((p) => p.bounding_box)}
              selectedIndex={clampedIndex}
              onSelect={setSelectedIndex}
              onChangeBox={handleBoxChange}
              onAddBox={addBox}
              onDeleteSelected={deleteSelected}
              onDuplicateSelected={duplicateSelected}
              onBringSelectedToFront={bringToFront}
              outlines={showOutlines ? "all" : "selected"}
              selectedLabel={
                selected
                  ? `box ${clampedIndex + 1} selected · ${boxExtent(selected.bounding_box)}`
                  : undefined
              }
            />
          )
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
          knownColours={knownColours}
        />
      </aside>
    </main>
  );
}
