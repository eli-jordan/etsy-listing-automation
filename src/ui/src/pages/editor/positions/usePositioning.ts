import { useEffect, useRef, useState } from "react";
import { getTemplateConfig } from "../../../api/calibrator";
import { getSettings } from "../../../api/workspaceSettings";
import type { ListingDetail, TemplateConfigState, TemplateSummary } from "../../../types";
import type { Focus } from "../focus";
import {
  type Positions,
  positionSignature,
  storedBox,
  withPose,
  withoutPosition,
} from "./document";
import { moved, nudged, resized, tilted } from "./gestures";
import type { LiveLook } from "./liveRenderer";
import {
  IDENTITY,
  type Limits,
  type Point,
  type Pose,
  type Quad,
  RESIDUAL_PIXELS,
  decompose,
  isIdentity,
  nearestAllowedPose,
  withinLimits,
} from "./pose";
import { type PositionReadiness, usePositionReadiness } from "./usePositionReadiness";

/**
 * Interactions: *Entry and the Adjust position switch*, *Adjusting*,
 * *Multiple templates*, *Position outside the limits*.
 */

export const NUDGE_DEBOUNCE_MS = 400;

export type Gesture = "move" | "scale" | "rotate";

export interface Layer {
  id: string;
  placement: string | null;
  templateBox: Quad;
  pose: Pose;
  stored: Quad | null;
  /** Spec, *Validation* rules 1-2. */
  refusal: PoseRefusal | null;
}

export type PoseRefusal = "limits" | "shape";

export interface Positioning extends Pick<PositionReadiness, "waiting" | "attempt" | "recheck"> {
  on: boolean;
  toggle: () => void;
  size: { w: number; h: number };
  layers: Layer[];
  selected: string;
  select: (id: string) => void;
  note: { text: string; warn: boolean } | null;
  reset: { label: string; run: (() => void) | null } | null;
  fit: (() => void) | null;
  ghost: boolean;
  aheadOfComposite: boolean;
  look: LiveLook;
  begin: (gesture: Gesture, id: string, point: Point) => void;
  move: (point: Point) => void;
  end: () => void;
  nudge: (key: string, shift: boolean) => boolean;
  loaded: (src: string) => void;
}

interface Args {
  detail: ListingDetail;
  template: string | null;
  pane: string;
  summary: TemplateSummary | undefined;
  savedComposite: string;
  saved: Positions | null | undefined;
  onUpdate: (patch: Record<string, unknown>) => void;
  onFlush: (() => void) | undefined;
  adjustScreen?: boolean;
}

export function positionTarget(
  focus: Focus | null,
  inListing: boolean,
  editable: boolean,
): { template: string | null; pane: string } {
  if (focus?.kind !== "template") return { template: null, pane: "" };
  const pane = `${focus.template}/${focus.colour ?? ""}`;
  return { template: editable && inListing ? focus.template : null, pane };
}

function useLimits(): Limits | null {
  const [limits, setLimits] = useState<Limits | null>(null);
  useEffect(() => {
    getSettings()
      .then((settings) => {
        const read = settings.template_positions;
        setLimits({
          scale: { min: read.scale?.min ?? 0.8, max: read.scale?.max ?? 1.1 },
          offset: read.offset,
          rotation: read.rotation,
        });
      })
      .catch(() => setLimits(null));
  }, []);
  return limits;
}

function useConfig(template: string | null): TemplateConfigState | null {
  const [configs, setConfigs] = useState<Record<string, TemplateConfigState | null>>({});
  useEffect(() => {
    if (template === null || template in configs) return;
    getTemplateConfig(template)
      .then((doc) => setConfigs((all) => ({ ...all, [template]: doc?.config ?? null })))
      .catch(() => setConfigs((all) => ({ ...all, [template]: null })));
  }, [template, configs]);
  return template === null ? null : (configs[template] ?? null);
}

export function useSavedPositions(detail: ListingDetail): Positions | null | undefined {
  const [saved, setSaved] = useState({
    at: detail.modified_at,
    positions: detail.template_positions,
  });
  if (saved.at !== detail.modified_at) {
    setSaved({ at: detail.modified_at, positions: detail.template_positions });
  }
  return saved.at === detail.modified_at ? saved.positions : detail.template_positions;
}

function layerOf(
  id: string,
  placement: string | null,
  box: Quad,
  stored: Quad | null,
  limits: Limits,
): Layer {
  if (stored === null) {
    return { id, placement, templateBox: box, pose: IDENTITY, stored, refusal: null };
  }
  try {
    const fit = decompose(box, stored);
    let refusal: Layer["refusal"] = withinLimits(fit.pose, limits) ? null : "limits";
    if (fit.residualPixels > RESIDUAL_PIXELS) refusal = "shape";
    return { id, placement, templateBox: box, pose: fit.pose, stored, refusal };
  } catch {
    return { id, placement, templateBox: box, pose: IDENTITY, stored, refusal: "shape" };
  }
}

function layersOf(
  config: TemplateConfigState,
  template: string,
  positions: Positions | null | undefined,
  limits: Limits,
): Layer[] {
  if (config.kind === "multiple") {
    return config.placements.map((p) =>
      layerOf(
        p.id,
        p.id,
        p.bounding_box as unknown as Quad,
        storedBox(positions, template, p.id),
        limits,
      ),
    );
  }
  const box = config.bounding_box as unknown as Quad;
  return [layerOf("design", null, box, storedBox(positions, template, null), limits)];
}

function noteFor(
  layer: Layer | undefined,
  on: boolean,
  layers: Layer[],
  config: TemplateConfigState,
  colours: number,
  template: string,
): Positioning["note"] {
  if (!on || layer === undefined) return null;
  if (layer.refusal === "limits") {
    return { text: "Outside the limits since the template's box moved", warn: true };
  }
  if (layer.refusal === "shape") {
    return { text: "Not a plain move, resize or tilt of the template's box", warn: true };
  }
  if (config.kind === "multiple") {
    const text =
      layers.length > 2 ? "Click another placement to switch" : "Click the other shirt to switch";
    return { text, warn: false };
  }
  if (config.kind === "colour-matrix") {
    return { text: `Applies to all ${colours} ${template} colours in this listing`, warn: false };
  }
  return null;
}

interface Drag {
  gesture: Gesture;
  id: string;
  start: Point;
  from: Pose;
}

interface Draft {
  template: string;
  id: string;
  pose: Pose;
}

function dragged(d: Drag, box: Quad, point: Point, limits: Limits): Pose {
  if (d.gesture === "move") return moved(box, d.from, d.start, point, limits);
  if (d.gesture === "scale") return resized(box, d.from, point, limits);
  return tilted(box, d.from, point, limits);
}

function stageable(
  config: TemplateConfigState | null,
  limits: Limits | null,
  summary: TemplateSummary | undefined,
): { config: TemplateConfigState; limits: Limits; size: { w: number; h: number } } | null {
  if (config === null || limits === null) return null;
  const w = summary?.width;
  const h = summary?.height;
  if (w == null || h == null) return null;
  return { config, limits, size: { w, h } };
}

function withDraft(base: Layer[], draft: Draft | null, name: string): Layer[] {
  return base.map((layer) =>
    draft?.template === name && draft.id === layer.id
      ? { ...layer, pose: draft.pose, refusal: null }
      : layer,
  );
}

function selectionOf(
  layers: Layer[],
  chosen: { template: string; id: string } | null,
  name: string,
): Layer | undefined {
  const fallback = layers.find((l) => l.refusal !== null) ?? layers[0];
  const pick = chosen?.template === name ? layers.find((l) => l.id === chosen.id) : undefined;
  return pick ?? fallback;
}

interface GestureContext {
  name: string;
  layers: Layer[];
  layer: Layer;
  on: boolean;
  limits: Limits;
  select: (id: string) => void;
  commit: (target: Layer, pose: Pose) => void;
}

function useGestures() {
  const [draft, setDraft] = useState<Draft | null>(null);
  const drag = useRef<Drag | null>(null);
  const draftRef = useRef<Draft | null>(null);
  const nudging = useRef<{ timer: ReturnType<typeof setTimeout>; save: () => void } | null>(null);
  useEffect(
    () => () => {
      if (nudging.current === null) return;
      clearTimeout(nudging.current.timer);
      nudging.current.save();
    },
    [],
  );

  function setDraftPose(next: Draft | null) {
    draftRef.current = next;
    setDraft(next);
  }

  function handlers(ctx: GestureContext): Pick<Positioning, "begin" | "move" | "end" | "nudge"> {
    const find = (id: string | undefined) => ctx.layers.find((l) => l.id === id);
    return {
      begin: (gesture, id, point) => {
        const target = find(id);
        if (!ctx.on || target === undefined) return;
        ctx.select(id);
        drag.current = { gesture, id, start: point, from: target.pose };
      },
      move: (point) => {
        const d = drag.current;
        const target = find(d?.id);
        if (d === null || target === undefined) return;
        setDraftPose({
          template: ctx.name,
          id: d.id,
          pose: dragged(d, target.templateBox, point, ctx.limits),
        });
      },
      end: () => {
        const target = find(drag.current?.id);
        drag.current = null;
        const pending = draftRef.current;
        if (pending === null || pending.id !== target?.id) return;
        ctx.commit(target, pending.pose);
      },
      nudge: (key, shift) => {
        const target = ctx.layer;
        const next = nudged(target.pose, key, shift, ctx.limits);
        if (next === null) return false;
        setDraftPose({ template: ctx.name, id: target.id, pose: next });
        if (nudging.current !== null) clearTimeout(nudging.current.timer);
        const save = () => {
          nudging.current = null;
          ctx.commit(target, next);
        };
        nudging.current = { timer: setTimeout(save, NUDGE_DEBOUNCE_MS), save };
        return true;
      },
    };
  }

  return { draft, clear: () => setDraftPose(null), handlers };
}

function lookOf({ renderer }: TemplateConfigState): LiveLook {
  if (renderer.type === "marigold") return { kind: "marigold" };
  const { enabled, blend, opacity } = renderer.config.shade;
  return { kind: "photo-warp", blend, opacity: enabled ? opacity : 0 };
}

function resetOf(
  layer: Layer,
  footEditing: boolean,
  adjustScreen: boolean,
  run: () => void,
): Positioning["reset"] {
  const label = layer.placement === null ? "Reset to template" : `Reset ${layer.placement}`;
  const positioned = layer.stored !== null || !isIdentity(layer.pose);
  if (adjustScreen) return { label, run: positioned ? run : null };
  return footEditing && positioned ? { label, run } : null;
}

function toggled(on: boolean, readiness: PositionReadiness, flip: () => void) {
  if (!on && readiness.waiting) readiness.refuse();
  else flip();
}

function refusal(readiness: PositionReadiness): Positioning["note"] {
  return readiness.note === null ? null : { text: readiness.note, warn: true };
}

export function usePositioning(args: Args): Positioning | null {
  const { detail, template, pane, summary, savedComposite, saved, onUpdate, onFlush } = args;
  const adjustScreen = args.adjustScreen === true;
  const limits = useLimits();
  const config = useConfig(template);
  const readiness = usePositionReadiness(config?.renderer.type === "marigold" ? template : null);
  const [adjust, setAdjust] = useState<{ pane: string; on: boolean } | null>(null);
  const [chosen, setChosen] = useState<{ template: string; id: string } | null>(null);
  const [edited, setEdited] = useState<string | null>(null);
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const gestures = useGestures();

  const ready = stageable(config, limits, summary);
  if (template === null || ready === null) return null;
  const name = template;
  const bounds = ready.limits;
  const stored = layersOf(ready.config, name, detail.template_positions, bounds);
  const layers = withDraft(stored, gestures.draft, name);
  const layer = selectionOf(layers, chosen, name);
  if (layer === undefined) return null;
  const on = adjust?.pane === pane ? adjust.on : stored.some((l) => l.refusal !== null);
  const footEditing = on || adjustScreen;

  // Deliberately this render's `detail`: a nudge's save builds on the positions its last key press saw.
  function write(positions: Positions | null) {
    onUpdate({ template_positions: positions });
    setEdited(name);
    // Pin Position mode on, so a pane that opened on because its stored box
    // was refused stays on once the box is fixed.
    setAdjust({ pane, on: true });
    onFlush?.();
  }

  function commit(target: Layer, pose: Pose) {
    write(
      withPose(detail.template_positions, name, target.placement, target.templateBox, pose, bounds),
    );
    gestures.clear();
  }

  const select = (id: string) => setChosen({ template: name, id });
  const savePending =
    positionSignature(detail.template_positions?.[name]) !== positionSignature(saved?.[name]);
  const unseen = edited === name && loadedSrc !== savedComposite;
  const colours = detail.media.filter((e) => typeof e !== "string" && e.template === name).length;
  const refused = layer.refusal === null ? null : layer.stored;

  return {
    on,
    toggle: () => toggled(on, readiness, () => setAdjust({ pane, on: !on })),
    waiting: readiness.waiting,
    attempt: readiness.attempt,
    recheck: readiness.recheck,
    size: ready.size,
    layers,
    selected: layer.id,
    select,
    note: refusal(readiness) ?? noteFor(layer, footEditing, layers, ready.config, colours, name),
    reset: resetOf(layer, footEditing, adjustScreen, () => {
      gestures.clear();
      write(withoutPosition(detail.template_positions, name, layer.placement));
    }),
    fit:
      footEditing && refused !== null
        ? () => {
            commit(layer, nearestAllowedPose(layer.templateBox, refused, bounds));
          }
        : null,
    ghost: on && !isIdentity(layer.pose),
    aheadOfComposite: on && (gestures.draft !== null || savePending || unseen),
    look: lookOf(ready.config),
    ...gestures.handlers({ name, layers, layer, on, limits: bounds, select, commit }),
    loaded: setLoadedSrc,
  };
}
