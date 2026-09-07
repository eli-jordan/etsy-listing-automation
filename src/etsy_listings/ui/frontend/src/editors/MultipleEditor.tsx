import { useCallback, useMemo, useState } from "react";
import { PreviewPanel, type PreviewJob } from "../components/PreviewPanel";
import { PrintRealismPanel } from "../components/PrintRealismPanel";
import { QuadEditor } from "../components/QuadEditor";
import { TestDesignPicker } from "../components/TestDesignPicker";
import { ViewTabs, type View } from "../components/ViewTabs";
import { usePreview } from "../hooks/usePreview";
import type { BoundingBox, MultipleTemplate, Placement } from "../types";

interface Props {
  templateName: string;
  config: MultipleTemplate;
  /** The scene photo's true pixel size -- the space every placement's box is
   * in. See `QuadEditor`'s `space`. */
  space: [number, number] | null;
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

/** The same rule the server uses for `TemplateSummary.status_reason`, so the
 * canvas and the rail can never disagree about whether this is finished. */
function uncolouredWarning(placements: Placement[]): string | null {
  const count = placements.filter((p) => !p.colour.trim()).length;
  if (count === 0) return null;
  const [noun, verb] = count === 1 ? ["box", "has"] : ["boxes", "have"];
  return `${count} ${noun} ${verb} no colour — can't mark calibrated yet`;
}

/**
 * The one output *is* the live composite of every placement, so there's no
 * separate gallery need here (unlike colour-matrix kind) -- the main preview
 * already shows everything at once.
 *
 * There is no bounding-box list panel any more. Everything it offered was
 * already reachable on the photo -- select, add, duplicate, reorder, delete,
 * drag -- except assigning a colour, and a colour is now a caption on the box
 * itself. A panel that duplicates the canvas is a second place to look and a
 * second place to be wrong about which box is which.
 */
export function MultipleEditor({
  templateName,
  config,
  space,
  onChange,
  design,
  onDesignChange,
  knownColours,
}: Props) {
  const [tab, setTab] = useState<View>("calibrate");
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

  // A chart composites every placement into one photo, so its preview is a
  // single full-size render -- what changes versus the canvas is the pixels,
  // not the composition.
  const jobs: PreviewJob[] = useMemo(
    () => [
      {
        id: templateName,
        label: templateName,
        body: {
          placements: config.placements,
          displace: config.displace,
          shade: config.shade,
        },
      },
    ],
    [templateName, config.placements, config.displace, config.shade],
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

  const handleColourChange = useCallback(
    (index: number, colour: string) =>
      onChange({
        ...config,
        placements: config.placements.map((p, i) => (i === index ? { ...p, colour } : p)),
      }),
    [config, onChange],
  );

  const clampedIndex = Math.min(selectedIndex, Math.max(config.placements.length - 1, 0));
  const warning = uncolouredWarning(config.placements);

  /** The box-editing operations, reached from the canvas -- one
   * implementation, whether you used the right-click menu, the Delete key or
   * the button. */
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
              x:
                p.x +
                (Math.max(...source.bounding_box.map((q) => q.x)) -
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
          <ViewTabs value={tab} onChange={setTab} />
          {tab === "calibrate" && (
            <label className="app__outline-toggle">
              <input
                type="checkbox"
                checked={showOutlines}
                onChange={(e) => setShowOutlines(e.target.checked)}
              />
              show all outlines
            </label>
          )}
        </div>
        {tab === "calibrate" &&
          (previewUrl && space ? (
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
                space={space}
                boxes={config.placements.map((p) => p.bounding_box)}
                selectedIndex={clampedIndex}
                onSelect={setSelectedIndex}
                onChangeBox={handleBoxChange}
                onAddBox={addBox}
                onDeleteSelected={deleteSelected}
                onDuplicateSelected={duplicateSelected}
                onBringSelectedToFront={bringToFront}
                outlines={showOutlines ? "all" : "selected"}
                labels={config.placements.map((p) => p.colour)}
                onLabelChange={handleColourChange}
                labelPlaceholder="assign colour…"
                labelSuggestions={knownColours}
              />
            )
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
        />
        {tab === "calibrate" && warning && <p className="app__warn">{warning}</p>}
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
      </aside>
    </main>
  );
}
