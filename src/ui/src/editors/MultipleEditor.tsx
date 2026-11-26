import { PreparationNotice } from "./PreparationNotice";
import type { ReactNode } from "react";
import type { PhotoSpace, PhotoWarpTemplate } from "../types";
import { useCallback, useMemo, useState } from "react";
import type { PreviewJob } from "../components/PreviewPanel";
import { QuadEditor } from "../components/QuadEditor";
import { usePreview } from "../hooks/usePreview";
import type { BoundingBox, MultipleTemplate, Placement } from "../types";
import { previewJobs } from "./marigoldEditorModel";
import { EditorShell } from "./EditorShell";

interface Props {
  rendererControls?: ReactNode;
  templateName: string;
  config: PhotoWarpTemplate<MultipleTemplate>;
  space: PhotoSpace | null;
  onChange: (config: MultipleTemplate) => void;
  design: string;
  onDesignChange: (design: string) => void;
  knownColours: string[];
}

const CENTRED_BOX: BoundingBox = [
  { x: 200, y: 150 },
  { x: 400, y: 150 },
  { x: 400, y: 350 },
  { x: 200, y: 350 },
];

/** Mirrors the server's `TemplateSummary.status_reason`, so canvas and rail agree. */
function uncolouredWarning(placements: Placement[]): string | null {
  const count = placements.filter((p) => !p.colour.trim()).length;
  if (count === 0) return null;
  const [noun, verb] = count === 1 ? ["box", "has"] : ["boxes", "have"];
  return `${count} ${noun} ${verb} no colour — can't mark calibrated yet`;
}

function PhotoWarpMultipleEditor(props: Props) {
  const { templateName, config, onChange, design, knownColours } = props;
  const [selectedIndex, setSelectedIndex] = useState(0);

  const previewUrl = usePreview(
    templateName,
    useMemo(
      () => ({
        placements: config.placements,
        renderer: config.renderer,
      }),
      [config.placements, config.renderer],
    ),
    design,
  );

  const jobs: PreviewJob[] = useMemo(
    () => previewJobs(config, [], templateName),
    [config, templateName],
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
          placements: [...placements, { id: crypto.randomUUID(), colour: "", bounding_box }],
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
          id: crypto.randomUUID(),
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
    <EditorShell
      {...props}
      rendererControls={props.rendererControls || null}
      previewUrl={previewUrl}
      jobs={jobs}
      outlineLabel="Show all design boxes"
      canvas={({ imageUrl, space: box_space, showOutlines }) =>
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
            imageUrl={imageUrl}
            space={box_space}
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
      }
      footer={warning ? <p className="app__warn">{warning}</p> : null}
    />
  );
}

export function MultipleEditor(props: Omit<Props, "config"> & { config: MultipleTemplate }) {
  const renderer = props.config.renderer;
  if (renderer.type !== "photo-warp") {
    return <PreparationNotice />;
  }
  return <PhotoWarpMultipleEditor {...props} config={{ ...props.config, renderer }} />;
}
