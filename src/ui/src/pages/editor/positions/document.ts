import type { Issue, ListingDetail } from "../../../types";
import {
  type Limits,
  type Pose,
  type Quad,
  compose,
  decompose,
  isIdentity,
  withinLimits,
} from "./pose";

/** A PATCH replaces the whole map (`null` removes it), so every edit here answers the next whole map. */
export type Positions = NonNullable<ListingDetail["template_positions"]>;
type Entry = Positions[string];
type BoxEntry = { bounding_box: Quad };

const isPlacements = (entry: Entry): entry is { placements: Record<string, BoxEntry> } =>
  "placements" in entry;

export function storedBox(
  positions: Positions | null | undefined,
  template: string,
  placement: string | null,
): Quad | null {
  const entry = positions?.[template];
  if (entry === undefined) return null;
  if (isPlacements(entry)) {
    return placement === null ? null : (entry.placements[placement]?.bounding_box ?? null);
  }
  return placement === null ? (entry.bounding_box as unknown as Quad) : null;
}

function finished(positions: Positions): Positions | null {
  return Object.keys(positions).length === 0 ? null : positions;
}

export function withoutPosition(
  positions: Positions | null | undefined,
  template: string,
  placement: string | null,
): Positions | null {
  const { [template]: entry, ...rest } = positions ?? {};
  if (entry !== undefined && placement !== null && isPlacements(entry)) {
    const siblings = Object.fromEntries(
      Object.entries(entry.placements).filter(([id]) => id !== placement),
    );
    if (Object.keys(siblings).length > 0) return { ...rest, [template]: { placements: siblings } };
  }
  return finished(rest);
}

function storable(box: Quad, pose: Pose, limits: Limits): Quad {
  const exact = compose(box, pose);
  const rounded = exact.map((p) => ({
    x: Math.round(p.x * 1e6) / 1e6,
    y: Math.round(p.y * 1e6) / 1e6,
  })) as unknown as Quad;
  return withinLimits(decompose(box, rounded).pose, limits) ? rounded : exact;
}

export function withPose(
  positions: Positions | null | undefined,
  template: string,
  placement: string | null,
  templateBox: Quad,
  pose: Pose,
  limits: Limits,
): Positions | null {
  if (isIdentity(pose)) return withoutPosition(positions, template, placement);
  const written: BoxEntry = { bounding_box: storable(templateBox, pose, limits) };
  const current = positions?.[template];
  const entry =
    placement === null
      ? written
      : {
          placements: {
            ...(current !== undefined && isPlacements(current) ? current.placements : {}),
            [placement]: written,
          },
        };
  return { ...(positions ?? {}), [template]: entry as Entry };
}

/** FNV-1a over the entry's JSON: a short stable tag for a preview URL. */
export function positionSignature(entry: Entry | undefined): string {
  if (entry === undefined) return "";
  let hash = 0x811c9dc5;
  for (const char of JSON.stringify(entry)) {
    hash = Math.imul(hash ^ char.charCodeAt(0), 0x01000193);
  }
  return (hash >>> 0).toString(36);
}

/** `listing_validation`'s pose refusals (rules 1 and 2): the stage shows these
 * and Fit within limits repairs them. Every other refusal under
 * `template_positions` names a key no stage can show -- a template not in
 * `media:`, a placement that is gone, the wrong shape for the template's
 * kind -- and its banner row removes the key instead. */
const POSE_REFUSAL =
  /\b(scales the design to|has (horizontal|vertical) offset|has rotation|is not a plain move)\b/;

const PREFIX = "template_positions.";
const PLACEMENTS = ".placements.";

export function removablePosition(
  issue: Issue,
): { template: string; placement: string | null } | null {
  if (!issue.where.startsWith(PREFIX) || POSE_REFUSAL.test(issue.message)) return null;
  const key = issue.where.slice(PREFIX.length);
  const split = key.indexOf(PLACEMENTS);
  if (split < 0) return { template: key, placement: null };
  return { template: key.slice(0, split), placement: key.slice(split + PLACEMENTS.length) };
}
