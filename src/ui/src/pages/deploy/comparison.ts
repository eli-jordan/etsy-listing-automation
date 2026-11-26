import {
  stageChanges,
  stageWillRun,
  type BelowCostRow,
  type ChangeDTO,
  type DriftDTO,
  type PlanDTO,
  type StagePlanDTO,
} from "../../types";

export type ImpactTag =
  "Images" | "Videos" | "Title" | "Description" | "Prices" | "Colours" | "Tags" | "Materials";

/** The title or the description. */
export interface TextBlock {
  before: string | null;
  after: string;
  changed: boolean;
}

/** The tags or the materials. */
export interface StringListBlock {
  before: string[];
  after: string[];
  added: string[];
  removed: string[];
  changed: boolean;
}

export interface ColoursBlock {
  before: string[];
  after: string[];
  added: string[];
  changed: boolean;
}

export interface PriceRange {
  min: string;
  max: string;
}

export interface PriceBlock {
  before: PriceRange | null;
  after: PriceRange | null;
  changed: boolean;
}

export type ImageBadge = "new" | "moved" | "removed" | null;

export interface AfterImageTile {
  rank: number;
  ref: string;
  badge: ImageBadge;
  movedFrom?: number;
  /** The stage reports a re-render as a media change whose ref is the same
   * before and after. Independent of `badge`: a re-rendered image can also move. */
  reRendered: boolean;
}

export interface BeforeImageTile {
  rank: number;
  ref: string | null;
  url: string | null;
  badge: ImageBadge;
  reRendered: boolean;
}

export interface ImagesBlock {
  before: BeforeImageTile[];
  after: AfterImageTile[];
  changed: boolean;
}

export interface AfterVideoTile {
  ref: string;
  slot: "featured" | "second";
  afterImages: number | null;
  badge: "new" | null;
}

/** One video Etsy has now, drawn from its own `thumbnail_url`. `ref` is
 * `null` for one this tool never uploaded. */
export interface BeforeVideoTile {
  videoId: number;
  ref: string | null;
  url: string | null;
  inactive: boolean;
  badge: "removed" | null;
}

export interface VideosBlock {
  before: BeforeVideoTile[];
  after: AfterVideoTile[];
  changed: boolean;
}

export interface PriceRow {
  size: string;
  before: string | null;
  after: string | null;
  changed: boolean;
  belowCost: boolean;
}

type DriftSource = "etsy" | "printify";

export interface DriftedField {
  key: `${DriftSource}:${string}`;
  path: string;
  label: string;
  source: DriftSource;
  live: string;
  after: string;
  expandable: boolean;
}

export interface Comparison {
  impacts: ImpactTag[];
  drifted: DriftedField[];
  hasEtsyListing: boolean;
  title: TextBlock | null;
  description: TextBlock | null;
  tags: StringListBlock | null;
  materials: StringListBlock | null;
  colours: ColoursBlock | null;
  price: PriceBlock | null;
  images: ImagesBlock | null;
  /** `etsy_videos`, shown under Etsy media; `null` when neither
   * side has a video. */
  videos: VideosBlock | null;
  priceRows: PriceRow[];
  belowCost: BelowCostRow[];
}

type StageName = StagePlanDTO["stage"];
type StagePlanFor<Name extends StageName> = Extract<StagePlanDTO, { stage: Name }>;

function findStage<Name extends StageName>(
  plan: PlanDTO,
  name: Name,
): StagePlanFor<Name> | undefined {
  return plan.stage_plans.find((stage): stage is StagePlanFor<Name> => stage.stage === name);
}

function findChange(stagePlan: StagePlanDTO | undefined, predicate: (c: ChangeDTO) => boolean) {
  return stagePlan === undefined ? undefined : stageChanges(stagePlan).find(predicate);
}

function asStrings(values: unknown[]): string[] {
  return values.filter((v): v is string => typeof v === "string");
}

function leadingAmount(rendered: string): number {
  return Number.parseFloat(rendered);
}

export function formatPriceRange(range: PriceRange | null): string {
  if (range === null) return "—";
  if (range.min === range.max) return range.min;
  const minAmount = range.min.split(" ")[0] ?? range.min;
  return `${minAmount}–${range.max}`;
}

function priceRange(rows: readonly { price: string }[]): PriceRange | null {
  const [first, ...rest] = rows;
  if (first === undefined) return null;
  let min = first;
  let max = first;
  for (const row of rest) {
    if (leadingAmount(row.price) < leadingAmount(min.price)) min = row;
    if (leadingAmount(row.price) > leadingAmount(max.price)) max = row;
  }
  return { min: min.price, max: max.price };
}

function buildTitle(stagePlan: StagePlanFor<"etsy_listing"> | undefined): TextBlock | null {
  const snapshot = stagePlan?.snapshot;
  if (!snapshot) return null;
  return {
    before: snapshot.live?.title ?? null,
    after: snapshot.desired.title ?? "",
    changed: findChange(stagePlan, (c) => c.kind === "field" && c.path === "title") !== undefined,
  };
}

function buildDescription(stagePlan: StagePlanFor<"etsy_listing"> | undefined): TextBlock | null {
  const snapshot = stagePlan?.snapshot;
  if (!snapshot) return null;
  return {
    before: snapshot.live?.description ?? null,
    after: snapshot.desired.description ?? "",
    changed:
      findChange(stagePlan, (c) => c.kind === "field" && c.path === "description") !== undefined,
  };
}

function buildStringList(
  stagePlan: StagePlanFor<"etsy_listing"> | undefined,
  field: "tags" | "materials",
): StringListBlock | null {
  const snapshot = stagePlan?.snapshot;
  if (!snapshot) return null;
  const change = findChange(stagePlan, (c) => c.kind === "list" && c.path === field);
  return {
    before: snapshot.live?.[field] ?? [],
    after: snapshot.desired[field],
    added: change && change.kind === "list" ? asStrings(change.added) : [],
    removed: change && change.kind === "list" ? asStrings(change.removed) : [],
    changed: change !== undefined,
  };
}

function buildColours(
  stagePlan: StagePlanFor<"printify_product"> | undefined,
): ColoursBlock | null {
  const snapshot = stagePlan?.snapshot;
  if (!snapshot) return null;
  const change = findChange(stagePlan, (c) => c.kind === "list" && c.path === "colors");
  return {
    before: [...new Set(snapshot.live.map((v) => v.colour))].sort(),
    after: [...new Set(snapshot.desired.map((v) => v.colour))].sort(),
    added: change && change.kind === "list" ? asStrings(change.added) : [],
    changed: change !== undefined,
  };
}

function buildPrice(stagePlan: StagePlanFor<"printify_product"> | undefined): PriceBlock | null {
  const snapshot = stagePlan?.snapshot;
  if (!snapshot) return null;
  return {
    before: priceRange(snapshot.live),
    after: priceRange(snapshot.desired),
    changed: stagePlan !== undefined && stageChanges(stagePlan).some((c) => c.kind === "price"),
  };
}

function buildPriceRows(
  stagePlan: StagePlanFor<"printify_product"> | undefined,
  belowCost: BelowCostRow[],
): PriceRow[] {
  const rows = new Map<string, PriceRow>();
  for (const change of stagePlan === undefined ? [] : stageChanges(stagePlan)) {
    if (change.kind !== "price") continue;
    if (rows.has(change.size)) continue;
    const isBelowCost = belowCost.some(
      (row) => row.size === change.size && (change.color === null || row.colour === change.color),
    );
    rows.set(change.size, {
      size: change.size,
      before: change.before,
      after: change.after,
      changed: true,
      belowCost: isBelowCost,
    });
  }
  return [...rows.values()];
}

function buildImages(stagePlan: StagePlanFor<"etsy_media"> | undefined): ImagesBlock | null {
  const snapshot = stagePlan?.snapshot;
  if (stagePlan === undefined || !snapshot) return null;

  const wasRankByRef = new Map<string, number>();
  for (const image of snapshot.live) {
    if (image.ref != null) wasRankByRef.set(image.ref, image.rank ?? 0);
  }
  const willBeUsed = new Set(snapshot.desired.map((entry) => entry.ref));
  const mediaChanges = stageChanges(stagePlan).filter((c) => c.kind === "media");
  const replaced = new Set(
    mediaChanges.flatMap((c) => (c.before !== null && c.before === c.after ? [c.after] : [])),
  );

  const after: AfterImageTile[] = snapshot.desired.map((entry) => {
    const previousRank = wasRankByRef.get(entry.ref);
    const tile = { rank: entry.rank, ref: entry.ref, reRendered: replaced.has(entry.ref) };
    if (previousRank === undefined) {
      return { ...tile, badge: "new", reRendered: false };
    }
    if (previousRank !== entry.rank) {
      return { ...tile, badge: "moved", movedFrom: previousRank };
    }
    return { ...tile, badge: null };
  });

  const before: BeforeImageTile[] = snapshot.live.map((image) => {
    const ref = image.ref ?? null;
    const used = ref !== null && willBeUsed.has(ref);
    return {
      rank: image.rank ?? 0,
      ref,
      url: image.url ?? null,
      badge: ref !== null && !used ? "removed" : null,
      reRendered: used && replaced.has(ref),
    };
  });

  return { before, after, changed: mediaChanges.length > 0 };
}

const VIDEO_SLOTS = ["videos.featured", "videos.second"] as const;

/**
 * The videos block. Every badge reads the stage's own changes: a slot
 * change names the ref before and after (`etsy_videos._changes`), so a ref
 * that arrives in a slot without leaving another is new, and one that leaves
 * without arriving is removed -- a swap is neither. New bytes on the same ref
 * (`.contents`) replace its upload, so it is both. A video this tool never
 * uploaded is swept whenever the stage runs, which the outcome says.
 */
function buildVideos(stagePlan: StagePlanFor<"etsy_videos"> | undefined): VideosBlock | null {
  const snapshot = stagePlan?.snapshot;
  if (!stagePlan || !snapshot) return null;
  if (snapshot.desired.length === 0 && snapshot.live.length === 0) return null;

  const changes = stageChanges(stagePlan).filter(
    (c): c is Extract<ChangeDTO, { kind: "field" }> =>
      c.kind === "field" && c.path.startsWith("videos."),
  );
  const slotRefs = (side: "before" | "after") =>
    new Set(
      changes
        .filter((c) => (VIDEO_SLOTS as readonly string[]).includes(c.path))
        .map((c) => c[side])
        .filter((ref): ref is string => typeof ref === "string"),
    );
  const arriving = slotRefs("after");
  const leaving = slotRefs("before");
  const replaced = new Set(
    VIDEO_SLOTS.flatMap((slot, index) =>
      changes.some((c) => c.path === `${slot}.contents`) ? [snapshot.desired[index]?.ref] : [],
    ).filter((ref): ref is string => ref !== undefined),
  );
  const sweeps = stageWillRun(stagePlan);

  return {
    after: snapshot.desired.map((video, index) => ({
      ref: video.ref,
      slot: index === 0 ? "featured" : "second",
      afterImages: video.after_images ?? null,
      badge:
        (arriving.has(video.ref) && !leaving.has(video.ref)) || replaced.has(video.ref)
          ? "new"
          : null,
    })),
    before: snapshot.live.map((video) => {
      const ref = video.ref ?? null;
      const removed =
        ref === null ? sweeps : (leaving.has(ref) && !arriving.has(ref)) || replaced.has(ref);
      return {
        videoId: video.video_id,
        ref,
        url: video.thumbnail_url ?? null,
        inactive: video.state !== "active",
        badge: removed ? "removed" : null,
      };
    }),
    changed: changes.length > 0,
  };
}

const DRIFT_LABELS: Record<string, string> = {
  is_supply: "Supply item",
  should_auto_renew: "Auto-renew",
  production_partner_ids: "Production partners",
  external: "Published on Etsy",
};

const NAMED_SETTINGS: Partial<Record<string, "shop_section" | "shipping_profile">> = {
  shop_section_id: "shop_section",
  shipping_profile_id: "shipping_profile",
};

function driftLabel(path: string, source: DriftedField["source"]): string {
  const words = path.replace(/_ids?$/, "").replace(/_/g, " ");
  const label = DRIFT_LABELS[path] ?? `${words.charAt(0).toUpperCase()}${words.slice(1)}`;
  return source === "printify" ? `${label} in Printify` : label;
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return Array.isArray(value) ? value.join(", ") : String(value);
}

function driftAfter(drift: DriftDTO, stagePlan: StagePlanDTO): string {
  const desired = stagePlan.stage === "etsy_listing" ? stagePlan.snapshot?.desired : undefined;
  const setting = NAMED_SETTINGS[drift.path];
  const named = setting && desired?.[setting];
  if (named) return named;
  const change = findChange(stagePlan, (c) => c.kind === "field" && c.path === drift.path);
  if (change?.kind === "field") return displayValue(change.after);
  return drift.last_applied_label ?? displayValue(drift.last_applied);
}

/** Printify republishes linked copy onto Etsy, so the same external edit can
 * appear in both stages. Show that event once, preferring the buyer-facing
 * Etsy observation when both sides are byte-for-byte identical. */
function uniqueDrifts(plan: PlanDTO): { drift: DriftDTO; stagePlan: StagePlanDTO }[] {
  const found = new Map<string, { drift: DriftDTO; stagePlan: StagePlanDTO }>();
  for (const stagePlan of plan.stage_plans) {
    for (const drift of stagePlan.drift) {
      const key = JSON.stringify([
        drift.path,
        drift.last_applied,
        drift.live,
        drift.last_applied_label,
        drift.live_label,
      ]);
      const previous = found.get(key);
      if (previous === undefined || previous.stagePlan.stage === "printify_product") {
        found.set(key, { drift, stagePlan });
      }
    }
  }
  return [...found.values()];
}

function buildDrifted(plan: PlanDTO): DriftedField[] {
  return uniqueDrifts(plan).map(({ drift, stagePlan }) => {
    const source = stagePlan.stage === "printify_product" ? "printify" : "etsy";
    return {
      key: `${source}:${drift.path}`,
      path: drift.path,
      label: driftLabel(drift.path, source),
      source,
      live: drift.live_label ?? displayValue(drift.live),
      after: driftAfter(drift, stagePlan),
      expandable: drift.path === "title" || drift.path === "description",
    };
  });
}

function impactsFor(
  colours: ColoursBlock | null,
  title: TextBlock | null,
  description: TextBlock | null,
  price: PriceBlock | null,
  tags: StringListBlock | null,
  materials: StringListBlock | null,
  images: ImagesBlock | null,
  videos: VideosBlock | null,
): ImpactTag[] {
  const impacts: ImpactTag[] = [];
  if (images?.changed) impacts.push("Images");
  if (videos?.changed) impacts.push("Videos");
  if (title?.changed) impacts.push("Title");
  if (description?.changed) impacts.push("Description");
  if (price?.changed) impacts.push("Prices");
  if (colours?.changed) impacts.push("Colours");
  if (tags?.changed) impacts.push("Tags");
  if (materials?.changed) impacts.push("Materials");
  return impacts;
}

export function buildComparison(plan: PlanDTO): Comparison {
  const productPlan = findStage(plan, "printify_product");
  const publishPlan = findStage(plan, "publish");
  const etsyListingPlan = findStage(plan, "etsy_listing");
  const etsyMediaPlan = findStage(plan, "etsy_media");

  const belowCost: BelowCostRow[] = publishPlan?.snapshot?.below_cost ?? [];

  const title = buildTitle(etsyListingPlan);
  const description = buildDescription(etsyListingPlan);
  const tags = buildStringList(etsyListingPlan, "tags");
  const materials = buildStringList(etsyListingPlan, "materials");
  const colours = buildColours(productPlan);
  const price = buildPrice(productPlan);
  const images = buildImages(etsyMediaPlan);
  const videos = buildVideos(findStage(plan, "etsy_videos"));
  const drifted = buildDrifted(plan);

  // Setting drifted copy back changes what buyers read as much as an edit does.
  const orDrifted = <Block extends { changed: boolean }>(block: Block | null, key: string) =>
    block && { ...block, changed: block.changed || drifted.some((d) => d.key === key) };

  return {
    impacts: impactsFor(
      colours,
      orDrifted(title, "etsy:title"),
      orDrifted(description, "etsy:description"),
      price,
      tags,
      materials,
      images,
      videos,
    ),
    drifted,
    hasEtsyListing: plan.etsy_listing_id !== null,
    title,
    description,
    tags,
    materials,
    colours,
    price,
    images,
    videos,
    priceRows: buildPriceRows(productPlan, belowCost),
    belowCost,
  };
}
