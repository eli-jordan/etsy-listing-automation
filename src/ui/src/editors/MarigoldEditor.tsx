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
  const placements: Placement[] =
    config.kind === "multiple"
      ? config.placements
      : [
          {
            id: "implicit",
            colour: config.kind === "single" ? (config.colour ?? "") : (colours[0] ?? ""),
            bounding_box: config.bounding_box,
            artwork: null,
          },
        ];
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
  const draftUndo = draft.strokes.length;
  const historyUndos = draft.undoSaved;
  const controls: MaskControls = {
    editing,
    setEditing,
    mode,
    setMode,
    diameter,
    setDiameter,
    canEdit: !!selected && !!placementState?.mask_available,
    canUndo:
      draftUndo > 0 || (!draft.automatic && (placementState?.undo_count ?? 0) > historyUndos),
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
    const p: Placement = { id: crypto.randomUUID(), colour: "", bounding_box, artwork: null };
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
  const jobs: PreviewJob[] = useMemo(
    () =>
      config.kind === "colour-matrix"
        ? colours.map((c) => ({
            id: c,
            label: c,
            body: { colour: c, bounding_box: config.bounding_box, renderer: config.renderer },
          }))
        : [
            {
              id: templateName,
              label: templateName,
              body:
                config.kind === "multiple"
                  ? { placements: config.placements, renderer: config.renderer }
                  : { bounding_box: config.bounding_box, renderer: config.renderer },
            },
          ],
    [config, colours, templateName],
  );
  const editorRevision = calibrationRevision || preparation?.config_revision || "";
  const editorBody =
    config.kind === "colour-matrix" ? jobs.find((job) => job.id === colour)?.body : jobs[0]?.body;
  const editorPreview = usePreview(
    templateName,
    editorRevision && editorBody
      ? { ...editorBody, calibration_revision: editorRevision, mask_edits: maskEdits }
      : null,
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
  const mapInputs = (value: TemplateConfigState | null) =>
    value?.renderer.type === "marigold"
      ? JSON.stringify({
          kind: value.kind,
          geometry:
            value.kind === "multiple"
              ? value.placements.map((p) => ({ id: p.id, bounding_box: p.bounding_box }))
              : value.bounding_box,
          inference: value.renderer.config.inference,
        })
      : null;
  const unsavedMaps = mapInputs(config) !== mapInputs(savedConfig) || maskEdits.length > 0;
  const awaitingSavedRevision =
    !!calibrationRevision && preparation?.config_revision !== calibrationRevision;
  const blocked =
    !marigoldMapsReady(preparation?.maps) ||
    unsavedMaps ||
    awaitingSavedRevision ||
    !!preparation?.active_job;
  return (
    <main className="app__main">
      <div className="app__preview">
        <div className="app__preview-bar">
          <ViewTabs value={tab} onChange={setTab} />
          <TestDesignPicker compact value={design} onChange={onDesignChange} />
          {tab === "calibrate" && config.kind === "colour-matrix" && colours.length > 1 && (
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
            <div className="app__outline-toggle">
              <BoxToggle checked={showBox} onChange={setShowBox} />
            </div>
          )}
        </div>
        {tab === "calibrate" && (
          <>
            <div className="mg-stage mg-editor-stage">
              {space ? (
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
                  {...(config.kind === "multiple"
                    ? {
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
                            mutate(
                              [...placements.filter((p) => p.id !== selected.id), selected],
                              selected.id,
                            );
                        },
                      }
                    : {})}
                  overlay={
                    <>
                      {placements.map((p, i) => {
                        const id = config.kind === "multiple" ? p.id : null;
                        const maskState = preparation?.placements.find(
                          (s) => s.placement_id === id,
                        );
                        return (
                          <PlacementOverlay
                            key={p.id}
                            showArtwork={!editorPreview}
                            box={p.bounding_box}
                            designUrl={`/api/designs/${encodeURIComponent(design)}/image`}
                            maskUrl={
                              maskState?.mask_available
                                ? maskUrl(templateName, id, false, revision)
                                : null
                            }
                            undoBases={
                              histories.revision === revision
                                ? (histories.values[id ?? "implicit"]?.strokes.map(
                                    (s) => s.before,
                                  ) ?? [])
                                : []
                            }
                            automaticMaskUrl={
                              maskState?.mask_available
                                ? maskUrl(templateName, id, true, revision)
                                : null
                            }
                            operations={
                              maskEdits.find((e) => e.placement_id === id)?.operations ?? []
                            }
                            space={space}
                            editing={editing && i === index}
                            mode={mode}
                            diameter={diameter}
                            onStroke={(stroke) => append(stroke, id)}
                          />
                        );
                      })}
                    </>
                  }
                />
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
          blocked={
            blocked
              ? unsavedMaps
                ? "Save your calibration changes before rendering."
                : awaitingSavedRevision
                  ? "Waiting for current calibration status. Reload the template if it changed elsewhere."
                  : (preparation?.maps.message ?? "Prepare the template first.")
              : null
          }
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
