import { ColourPicker } from "./ColourPicker";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  getMaskHistory,
  type MaskHistory,
  maskUrl,
  type MaskEdit,
  type MaskOperation,
  type Preparation,
} from "../api/preparation";
import { usePreview } from "../hooks/usePreview";
import { templatePhotoUrl } from "../api/calibrator";
import { PreviewPanel, type PreviewJob } from "../components/PreviewPanel";
import { MarigoldRealismPanel } from "../components/MarigoldRealismPanel";
import { BoxToggle } from "../components/BoxToggle";
import { MaskBrushDock, type MaskControls } from "../components/MaskToolbar";
import { PlacementOverlay } from "../components/PlacementOverlay";
import { marigoldMapsReady } from "../components/preparationLabel";
import { maskDraft } from "../components/maskDraft";
import { QuadEditor } from "../components/QuadEditor";
import { TestDesignPicker } from "../components/TestDesignPicker";
import { ViewTabs, type View } from "../components/ViewTabs";
import type { BoundingBox, Renderer, TemplateConfigState, Placement } from "../types";
import "../components/marigold.css";
import {
  canUndoMask,
  editorPlacements,
  editorPreviewRequest,
  marigoldMapInputs,
  previewBlocker,
  previewJobs,
  undoBases,
} from "./marigoldEditorModel";

interface Props {
  templateName: string;
  config: TemplateConfigState & { renderer: Extract<Renderer, { type: "marigold" }> };
  space: [number, number] | null;
  colours: string[];
  knownColours: string[];
  design: string;
  onDesignChange: (design: string) => void;
  onChange: (config: TemplateConfigState) => void;
  preparation: Preparation | null;
  rendererControls: ReactNode;
  calibrationRevision?: string;
  maskEdits: MaskEdit[];
  onMaskEdits: (edits: MaskEdit[]) => void;
  savedConfig: TemplateConfigState | null;
  onPrepare: () => void;
  onPreviewPending?: (pending: boolean) => void;
}
/** The view tabs and the calibrate view's pickers: colour (for a colour
 * matrix with a choice) and the design box toggle. */
function PreviewBar({
  tab,
  onTabChange,
  design,
  onDesignChange,
  colour,
  colours,
  onColourChange,
  showBox,
  onShowBoxChange,
}: {
  tab: View;
  onTabChange: (tab: View) => void;
  design: string;
  onDesignChange: (design: string) => void;
  colour: string;
  colours: string[];
  onColourChange: (colour: string) => void;
  showBox: boolean;
  onShowBoxChange: (show: boolean) => void;
}) {
  const calibrating = tab === "calibrate";
  return (
    <div className="app__preview-bar">
      <ViewTabs value={tab} onChange={onTabChange} />
      <TestDesignPicker compact value={design} onChange={onDesignChange} />
      {calibrating && colours.length > 1 && (
        <ColourPicker colour={colour} colours={colours} onChange={onColourChange} />
      )}
      {calibrating && (
        <div className="app__outline-toggle">
          <BoxToggle checked={showBox} onChange={onShowBoxChange} />
        </div>
      )}
    </div>
  );
}

/** Each placement's artwork and mask, with the brush on the one being
 * edited. */
function PlacementOverlays({
  placements,
  multiple,
  preparation,
  showArtwork,
  design,
  templateName,
  revision,
  histories,
  maskEdits,
  space,
  editingIndex,
  mode,
  diameter,
  onStroke,
}: {
  placements: Placement[];
  multiple: boolean;
  preparation: Preparation | null;
  showArtwork: boolean;
  design: string;
  templateName: string;
  revision: string;
  histories: { revision: string; values: Record<string, MaskHistory> };
  maskEdits: MaskEdit[];
  space: [number, number];
  editingIndex: number | null;
  mode: "mask" | "unmask";
  diameter: number;
  onStroke: (stroke: MaskOperation, id: string | null) => void;
}) {
  return (
    <>
      {placements.map((p, i) => {
        const id = multiple ? p.id : null;
        const maskState = preparation?.placements.find((s) => s.placement_id === id);
        const masked = !!maskState?.mask_available;
        return (
          <PlacementOverlay
            key={p.id}
            showArtwork={showArtwork}
            box={p.bounding_box}
            designUrl={`/api/designs/${encodeURIComponent(design)}/image`}
            maskUrl={masked ? maskUrl(templateName, id, false, revision) : null}
            undoBases={undoBases(histories, revision, id)}
            automaticMaskUrl={masked ? maskUrl(templateName, id, true, revision) : null}
            operations={maskEdits.find((e) => e.placement_id === id)?.operations ?? []}
            space={space}
            editing={i === editingIndex}
            mode={mode}
            diameter={diameter}
            onStroke={(stroke) => onStroke(stroke, id)}
          />
        );
      })}
    </>
  );
}

export function MarigoldEditor({
  templateName,
  config,
  space,
  colours,
  knownColours,
  design,
  onDesignChange,
  onChange,
  preparation,
  rendererControls,
  calibrationRevision,
  maskEdits,
  onMaskEdits,
  savedConfig,
  onPrepare,
  onPreviewPending,
}: Props) {
  const [histories, setHistories] = useState<{
    revision: string;
    values: Record<string, MaskHistory>;
  }>({ revision: "", values: {} });
  const [tab, setTab] = useState<View>("calibrate");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedColour, setSelectedColour] = useState<string | null>(null);
  const colour =
    selectedColour && colours.includes(selectedColour) ? selectedColour : (colours[0] ?? "");

  const [editing, setEditing] = useState(false);
  useEffect(() => {
    if (!editing) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) setEditing(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [editing]);
  const [showBox, setShowBox] = useState(true);
  const [mode, setMode] = useState<"mask" | "unmask">("mask");
  const [diameter, setDiameter] = useState(24);
  const placements = editorPlacements(config, colours);
  const index = Math.max(
    0,
    placements.findIndex((p) => p.id === selectedId),
  );
  const selected = placements[index];
  const placementId = config.kind === "multiple" ? (selected?.id ?? null) : null;
  const edit = maskEdits.find((e) => e.placement_id === placementId);
  const operations = edit?.operations ?? [];
  function append(operation: MaskOperation, id = placementId) {
    const existing = maskEdits.find((e) => e.placement_id === id)?.operations ?? [];
    onMaskEdits([
      ...maskEdits.filter((e) => e.placement_id !== id),
      { placement_id: id, operations: [...existing, operation] },
    ]);
  }
  const placementState = preparation?.placements.find((p) => p.placement_id === placementId);
  const draft = maskDraft(operations);
  const controls: MaskControls = {
    editing,
    setEditing,
    mode,
    setMode,
    diameter,
    setDiameter,
    canEdit: !!selected && !!placementState?.mask_available,
    canUndo: canUndoMask(draft, placementState?.undo_count ?? 0),
    undo: () => append({ type: "undo" }),
    reset: () => append({ type: "reset" }),
  };
  function changeBox(i: number, bounding_box: BoundingBox) {
    if (config.kind === "multiple")
      onChange({
        ...config,
        placements: config.placements.map((p, n) => (n === i ? { ...p, bounding_box } : p)),
      });
    else onChange({ ...config, bounding_box });
  }
  function mutate(next: Placement[], select: string | null) {
    if (config.kind !== "multiple") return;
    onChange({ ...config, placements: next });
    setSelectedId(select);
    setEditing(false);
  }
  function add() {
    const bounding_box: BoundingBox = selected
      ? (selected.bounding_box.map((p) => ({ x: p.x + 40, y: p.y + 20 })) as BoundingBox)
      : [
          { x: 200, y: 150 },
          { x: 400, y: 150 },
          { x: 400, y: 350 },
          { x: 200, y: 350 },
        ];
    const p: Placement = { id: crypto.randomUUID(), colour: "", bounding_box };
    mutate([...placements, p], p.id);
  }
  function duplicate() {
    if (!selected) return;
    const copy = {
      ...selected,
      id: crypto.randomUUID(),
      bounding_box: selected.bounding_box.map((p) => ({ x: p.x + 40, y: p.y + 20 })) as BoundingBox,
    };
    const next = [...placements];
    next.splice(index + 1, 0, copy);
    mutate(next, copy.id);
  }
  /** QuadEditor's placement controls, which only a multiple template has. */
  function placementEditing() {
    if (config.kind !== "multiple") return {};
    return {
      labels: placements.map((p) => p.colour),
      labelSuggestions: knownColours,
      labelPlaceholder: "assign colour",
      onLabelChange: (i: number, c: string) =>
        mutate(
          placements.map((p, n) => (n === i ? { ...p, colour: c } : p)),
          placements[i]?.id ?? null,
        ),
      onAddBox: add,
      onDuplicateSelected: duplicate,
      onDeleteSelected: () => {
        if (!selected) return;
        mutate(
          placements.filter((p) => p.id !== selected.id),
          null,
        );
        onMaskEdits(maskEdits.filter((e) => e.placement_id !== selected.id));
      },
      onBringSelectedToFront: () => {
        if (selected)
          mutate([...placements.filter((p) => p.id !== selected.id), selected], selected.id);
      },
    };
  }
  /** The calibrate view's canvas: the photo (or its live preview) with
   * every placement's box, artwork and mask. */
  function calibrationCanvas(space: [number, number]) {
    return (
      <QuadEditor
        imageUrl={
          editorPreview ??
          templatePhotoUrl(templateName, config.kind === "colour-matrix" ? colour : null)
        }
        space={space}
        boxes={placements.map((p) => p.bounding_box)}
        selectedIndex={index}
        onSelect={(i) => {
          setSelectedId(placements[i]?.id ?? null);
          setEditing(false);
        }}
        onChangeBox={changeBox}
        outlines={showBox ? "all" : "none"}
        interactive={!editing}
        {...placementEditing()}
        overlay={
          <PlacementOverlays
            placements={placements}
            multiple={config.kind === "multiple"}
            preparation={preparation}
            showArtwork={!editorPreview}
            design={design}
            templateName={templateName}
            revision={revision}
            histories={histories}
            maskEdits={maskEdits}
            space={space}
            editingIndex={editing ? index : null}
            mode={mode}
            diameter={diameter}
            onStroke={append}
          />
        }
      />
    );
  }
  const jobs: PreviewJob[] = useMemo(
    () => previewJobs(config, colours, templateName),
    [config, colours, templateName],
  );
  const editorRevision = calibrationRevision || preparation?.config_revision || "";
  const editorPreview = usePreview(
    templateName,
    editorPreviewRequest(config.kind, jobs, colour, editorRevision, maskEdits),
    design,
    true,
    onPreviewPending,
  );
  const revision = preparation?.config_revision ?? "";
  const placementKey = JSON.stringify(
    preparation?.placements.filter((p) => p.mask_available).map((p) => p.placement_id) ?? [],
  );
  useEffect(() => {
    let active = true;
    const ids: (string | null)[] = JSON.parse(placementKey) as (string | null)[];
    void Promise.all(
      ids.map(async (id) => [id ?? "implicit", await getMaskHistory(templateName, id)] as const),
    )
      .then((rows) => {
        if (active) setHistories({ revision, values: Object.fromEntries(rows) });
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [templateName, revision, placementKey]);
  const unsavedMaps =
    marigoldMapInputs(config) !== marigoldMapInputs(savedConfig) || maskEdits.length > 0;
  const awaitingSavedRevision =
    !!calibrationRevision && preparation?.config_revision !== calibrationRevision;
  const blocked = previewBlocker({
    mapsReady: marigoldMapsReady(preparation?.maps),
    unsavedMaps,
    awaitingSavedRevision,
    activeJob: !!preparation?.active_job,
    mapsMessage: preparation?.maps.message,
  });
  return (
    <main className="app__main">
      <div className="app__preview">
        <PreviewBar
          tab={tab}
          onTabChange={setTab}
          design={design}
          onDesignChange={onDesignChange}
          colour={colour}
          colours={config.kind === "colour-matrix" ? colours : []}
          onColourChange={setSelectedColour}
          showBox={showBox}
          onShowBoxChange={setShowBox}
        />
        {tab === "calibrate" && (
          <>
            <div className="mg-stage mg-editor-stage">
              {space ? (
                calibrationCanvas(space)
              ) : (
                <p className="app__loading">No readable scene photo.</p>
              )}
              {space && <MaskBrushDock controls={controls} />}
            </div>
          </>
        )}
        <PreviewPanel
          fullQuality
          templateName={templateName}
          jobs={jobs}
          design={design}
          active={tab === "preview"}
          blocked={blocked}
          onPrepare={onPrepare}
          prepareLabel={
            preparation?.maps.reason === "photo_changed"
              ? "Reset masks and prepare"
              : "Prepare template"
          }
          identity={preparation?.maps.content_digest ?? ""}
        />
      </div>
      <aside className="app__controls">
        {rendererControls}
        <MarigoldRealismPanel
          value={config.renderer.config.appearance}
          onChange={(appearance) =>
            onChange({
              ...config,
              renderer: { ...config.renderer, config: { ...config.renderer.config, appearance } },
            })
          }
        />
      </aside>
    </main>
  );
}
