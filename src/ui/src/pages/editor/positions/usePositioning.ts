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

/**
 * Position mode's state for the one template entry the preview pane shows
 * (interactions: *Entry and the Adjust position switch*, *Adjusting*,
 * *Multiple templates*, *Position outside the limits*).
 *
 * A gesture edits a draft pose; it is saved once it completes -- pointer
 * release, or {@link NUDGE_DEBOUNCE_MS} after the last arrow key -- through
 * the editor's ordinary `onUpdate` and an immediate flush, so the head's save
 * status behaves as for any other field. Between that save and the saved
 * composite loading, the stage draws the draft overlay.
 */

/** Interactions, *Saving*: "a nudge after a short debounce (about 400 ms)". */
export const NUDGE_DEBOUNCE_MS = 400;

export type Gesture = "move" | "scale" | "rotate";

export interface Layer {
  id: string;
  /** The placement ID of a `multiple` template, which labels its box. */
  placement: string | null;
  /** The template's own box. */
  box: Quad;
  pose: Pose;
  /** What `listing.yaml` holds for it, when anything. */
  stored: Quad | null;
  /** Why `plan` refuses the stored box (spec, *Validation* rules 1-2). */
  invalid: "limits" | "shape" | null;
}

export interface Positioning {
  on: boolean;
  toggle: () => void;
  size: { w: number; h: number };
  layers: Layer[];
  selected: string;
  select: (id: string) => void;
  note: { text: string; warn: boolean } | null;
  reset: { label: string; run: () => void } | null;
  fit: (() => void) | null;
  ghost: boolean;
  overlay: boolean;
  begin: (gesture: Gesture, id: string, point: Point) => void;
  move: (point: Point) => void;
  end: () => void;
  nudge: (key: string, shift: boolean) => boolean;
  loaded: (src: string) => void;
}

interface Args {
  detail: ListingDetail;
  /** The entry the pane shows, when it is a template entry in this listing. */
  template: string | null;
  /** Which pane that is -- a template and colour. The switch belongs to it,
   * so selecting another reel tile turns it off. */
  pane: string;
  summary: TemplateSummary | undefined;
  /** The composite the stage shows: the saved listing's. */
  picture: string;
  /** Saved positions, as the last server response had them. */
  saved: Positions | null | undefined;
  onUpdate: (patch: Record<string, unknown>) => void;
  onFlush: (() => void) | undefined;
}

/** Which template entry the pane may position, and which pane it is. Only
 * a saved listing's own entries: a listing template or a batch never
 * carries positions (spec, *Scope and decisions*), and an unnamed draft has
 * no saved composite to adjust. */
export function positionTarget(
  focus: Focus | null,
  inListing: boolean,
  editable: boolean,
): { template: string | null; pane: string } {
  if (focus?.kind !== "template") return { template: null, pane: "" };
  const pane = `${focus.template}/${focus.colour ?? ""}`;
  return { template: editable && inListing ? focus.template : null, pane };
}

/** The workspace limits, read once (interactions, *What the production
 * implementation must finish*). `null` until read, or when unreadable. */
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

/** Each template's saved geometry, fetched the first time it is shown. */
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

/** Saved positions: what the last server response held. `modified_at` moves
 * only when a response lands, which is what makes the preview URL change with
 * the *saved* position rather than the optimistic one. */
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
  if (stored === null) return { id, placement, box, pose: IDENTITY, stored, invalid: null };
  try {
    const fit = decompose(box, stored);
    let invalid: Layer["invalid"] = withinLimits(fit.pose, limits) ? null : "limits";
    if (fit.residual > RESIDUAL_PIXELS) invalid = "shape";
    return { id, placement, box, pose: fit.pose, stored, invalid };
  } catch {
    return { id, placement, box, pose: IDENTITY, stored, invalid: "shape" };
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
  if (layer.invalid === "limits") {
    return { text: "Outside the limits since the template's box moved", warn: true };
  }
  if (layer.invalid === "shape") {
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

/** What the stage needs before it can show handles; `null` means no switch --
 * nothing loaded yet, or no photo size. Both renderers take positions. */
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

/** The draft pose stands in for the stored one while a gesture is unsaved. */
function withDraft(base: Layer[], draft: Draft | null, name: string): Layer[] {
  return base.map((layer) =>
    draft?.template === name && draft.id === layer.id
      ? { ...layer, pose: draft.pose, invalid: null }
      : layer,
  );
}

/** The chosen placement, else the first refused one, else the first in the
 * template's order (interactions, *Multiple templates*). */
function selectionOf(
  layers: Layer[],
  chosen: { template: string; id: string } | null,
  name: string,
): Layer | undefined {
  const fallback = layers.find((l) => l.invalid !== null) ?? layers[0];
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

/** The handles' state: the drag under way, the draft it has made, and the
 * nudge waiting out its debounce. */
function useGestures() {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<Drag | null>(null);
  const draftRef = useRef<Draft | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
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
        setDragging(true);
      },
      move: (point) => {
        const d = drag.current;
        const target = find(d?.id);
        if (d === null || target === undefined) return;
        setDraftPose({
          template: ctx.name,
          id: d.id,
          pose: dragged(d, target.box, point, ctx.limits),
        });
      },
      end: () => {
        const target = find(drag.current?.id);
        drag.current = null;
        setDragging(false);
        const pending = draftRef.current;
        if (pending === null || pending.id !== target?.id) return;
        ctx.commit(target, pending.pose);
      },
      nudge: (key, shift) => {
        const target = ctx.layer;
        const next = nudged(target.pose, key, shift, ctx.limits);
        if (next === null) return false;
        setDraftPose({ template: ctx.name, id: target.id, pose: next });
        if (timer.current !== null) clearTimeout(timer.current);
        timer.current = setTimeout(() => {
          timer.current = null;
          ctx.commit(target, next);
        }, NUDGE_DEBOUNCE_MS);
        return true;
      },
    };
  }

  return { draft, dragging, clear: () => setDraftPose(null), handlers };
}

function resetOf(layer: Layer, on: boolean, run: () => void): Positioning["reset"] {
  if (!on || (layer.stored === null && isIdentity(layer.pose))) return null;
  return {
    label: layer.placement === null ? "Reset to template" : `Reset ${layer.placement}`,
    run,
  };
}

export function usePositioning(args: Args): Positioning | null {
  const { detail, template, pane, summary, picture, saved, onUpdate, onFlush } = args;
  const limits = useLimits();
  const config = useConfig(template);
  /** The switch, per pane: it belongs to the template it was turned on for. */
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
  // Opened on by a refused *stored* box: a draft that looks valid must not
  // switch the mode off under the pointer or the keyboard.
  const on = adjust?.pane === pane ? adjust.on : stored.some((l) => l.invalid !== null);

  // `detail` as of this render. A nudge's save runs from the render of its
  // last key press, so it builds on the positions shown then.
  function write(positions: Positions | null) {
    onUpdate({ template_positions: positions });
    setEdited(name);
    // Writes happen only in Position mode. Pin it, so a pane that opened on
    // because its stored box was refused stays on once the box is fixed.
    setAdjust({ pane, on: true });
    onFlush?.();
  }

  function commit(target: Layer, pose: Pose) {
    write(withPose(detail.template_positions, name, target.placement, target.box, pose, bounds));
    gestures.clear();
  }

  const select = (id: string) => setChosen({ template: name, id });
  const savePending =
    positionSignature(detail.template_positions?.[name]) !== positionSignature(saved?.[name]);
  const unseen = edited === name && loadedSrc !== picture;
  const colours = detail.media.filter((e) => typeof e !== "string" && e.template === name).length;
  const refused = layer.invalid === null ? null : layer.stored;

  return {
    on,
    toggle: () => setAdjust({ pane, on: !on }),
    size: ready.size,
    layers,
    selected: layer.id,
    select,
    note: noteFor(layer, on, layers, ready.config, colours, name),
    reset: resetOf(layer, on, () => {
      gestures.clear();
      write(withoutPosition(detail.template_positions, name, layer.placement));
    }),
    fit:
      on && refused !== null
        ? () => {
            commit(layer, nearestAllowedPose(layer.box, refused, bounds));
          }
        : null,
    ghost: on && !isIdentity(layer.pose),
    overlay: on && (gestures.dragging || gestures.draft !== null || savePending || unseen),
    ...gestures.handlers({ name, layers, layer, on, limits: bounds, select, commit }),
    loaded: setLoadedSrc,
  };
}
