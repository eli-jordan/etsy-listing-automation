import type { BelowCostRow, ChangeDTO, PlanDTO, StagePlanDTO } from "../../types";

/**
 * Pure: `Plan` snapshots + `Change`s -> before/after blocks, impact tags,
 * price rows, image badges (docs/deploy-changes.md decisions 3/4, spec's
 * "Comparison"/"Price table" elements).
 *
 * This is the frontend half of A30: each stage exposed a snapshot of its own
 * domain facts so the comparison could be composed here instead of on the
 * server, and A2 still holds one level up -- every `changed` flag below
 * traces to a `Change` object the engine already emitted, never to this
 * module comparing two snapshot values itself. A block's *content* (the
 * unchanged context alongside a change) comes from the snapshot; whether it
 * is *tinted* comes only from `stage_plan.changes`.
 *
 * Follows the mock and the spec's own reading order -- gallery first, down
 * through tags and materials -- because that is a buyer's reading order on
 * an Etsy listing page, and matching it is what makes the comparison quick
 * to check by eye (decision 3's "the blocks follow a buyer's reading order").
 * Description and materials were not in the original five (the mock never
 * had a block for either); added once their absence let a pending edit reach
 * Apply with no before/after shown for it at all.
 */

export type ImpactTag =
  "Images" | "Title" | "Description" | "Prices" | "Colours" | "Tags" | "Materials";

export interface TitleBlock {
  before: string | null;
  after: string;
  changed: boolean;
}

/** Same shape as `TitleBlock` -- kept as its own type because "description"
 * reading as a `TitleBlock` at a call site would be confusing, not because
 * the two ever need to diverge. */
export interface DescriptionBlock {
  before: string | null;
  after: string;
  changed: boolean;
}

export interface TagsBlock {
  before: string[];
  after: string[];
  added: string[];
  removed: string[];
  changed: boolean;
}

/** Same shape as `TagsBlock`, same reasoning. */
export interface MaterialsBlock {
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
}

export interface BeforeImageTile {
  rank: number;
  ref: string | null;
  url: string | null;
  badge: ImageBadge;
}

export interface ImagesBlock {
  before: BeforeImageTile[];
  after: AfterImageTile[];
  changed: boolean;
}

export interface PriceRow {
  size: string;
  before: string | null;
  after: string | null;
  changed: boolean;
  belowCost: boolean;
}

export interface Comparison {
  /** Which of the parts of the listing the plan touches, for the headline's
   * tags -- in reading order, not the order `Change`s happened to be emitted
   * in. */
  impacts: ImpactTag[];
  /** Whether `plan.etsy_listing_id` names a real listing -- `false` gets a
   * single "After apply" column with a *Not on Etsy yet* note (decision 3),
   * never an empty "On Etsy now" one. */
  hasEtsyListing: boolean;
  title: TitleBlock | null;
  description: DescriptionBlock | null;
  tags: TagsBlock | null;
  materials: MaterialsBlock | null;
  colours: ColoursBlock | null;
  price: PriceBlock | null;
  images: ImagesBlock | null;
  priceRows: PriceRow[];
  /** `publish`'s own below-cost rows, verbatim -- never re-derived by
   * comparing a row's price against its cost here, which is exactly the
   * second copy of the rule A30 exists to prevent. */
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
  return stagePlan?.changes.find(predicate);
}

function asStrings(values: unknown[]): string[] {
  return values.filter((v): v is string => typeof v === "string");
}

/** `"349 NOK"` -> `349`. Parses only the leading amount -- callers already
 * know the currency is the listing's own from context, and this exists
 * purely to compare two `Money` strings' magnitudes for a min/max range. */
function moneyAmount(rendered: string): number {
  return Number.parseFloat(rendered);
}

function priceRange(rows: readonly { price: string }[]): PriceRange | null {
  const [first, ...rest] = rows;
  if (first === undefined) return null;
  let min = first;
  let max = first;
  for (const row of rest) {
    if (moneyAmount(row.price) < moneyAmount(min.price)) min = row;
    if (moneyAmount(row.price) > moneyAmount(max.price)) max = row;
  }
  return { min: min.price, max: max.price };
}

function buildTitle(stagePlan: StagePlanFor<"etsy_listing"> | undefined): TitleBlock | null {
  const snapshot = stagePlan?.snapshot;
  if (!snapshot) return null;
  return {
    before: snapshot.live?.title ?? null,
    after: snapshot.desired.title ?? "",
    changed: findChange(stagePlan, (c) => c.kind === "field" && c.path === "title") !== undefined,
  };
}

function buildDescription(
  stagePlan: StagePlanFor<"etsy_listing"> | undefined,
): DescriptionBlock | null {
  const snapshot = stagePlan?.snapshot;
  if (!snapshot) return null;
  return {
    before: snapshot.live?.description ?? null,
    after: snapshot.desired.description ?? "",
    changed:
      findChange(stagePlan, (c) => c.kind === "field" && c.path === "description") !== undefined,
  };
}

function buildTags(stagePlan: StagePlanFor<"etsy_listing"> | undefined): TagsBlock | null {
  const snapshot = stagePlan?.snapshot;
  if (!snapshot) return null;
  const change = findChange(stagePlan, (c) => c.kind === "list" && c.path === "tags");
  return {
    before: snapshot.live?.tags ?? [],
    after: snapshot.desired.tags,
    added: change && change.kind === "list" ? asStrings(change.added) : [],
    removed: change && change.kind === "list" ? asStrings(change.removed) : [],
    changed: change !== undefined,
  };
}

function buildMaterials(
  stagePlan: StagePlanFor<"etsy_listing"> | undefined,
): MaterialsBlock | null {
  const snapshot = stagePlan?.snapshot;
  if (!snapshot) return null;
  const change = findChange(stagePlan, (c) => c.kind === "list" && c.path === "materials");
  return {
    before: snapshot.live?.materials ?? [],
    after: snapshot.desired.materials,
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
    changed: (stagePlan?.changes ?? []).some((c) => c.kind === "price"),
  };
}

function buildPriceRows(
  stagePlan: StagePlanFor<"printify_product"> | undefined,
  belowCost: BelowCostRow[],
): PriceRow[] {
  const rows = new Map<string, PriceRow>();
  for (const change of stagePlan?.changes ?? []) {
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
  if (!snapshot) return null;

  const wasRankByRef = new Map<string, number>();
  for (const image of snapshot.live) {
    if (image.ref != null) wasRankByRef.set(image.ref, image.rank ?? 0);
  }
  const willBeUsed = new Set(snapshot.desired.map((entry) => entry.ref));

  const after: AfterImageTile[] = snapshot.desired.map((entry) => {
    const previousRank = wasRankByRef.get(entry.ref);
    if (previousRank === undefined) {
      return { rank: entry.rank, ref: entry.ref, badge: "new" };
    }
    if (previousRank !== entry.rank) {
      return { rank: entry.rank, ref: entry.ref, badge: "moved", movedFrom: previousRank };
    }
    return { rank: entry.rank, ref: entry.ref, badge: null };
  });

  const before: BeforeImageTile[] = snapshot.live.map((image) => ({
    rank: image.rank ?? 0,
    ref: image.ref ?? null,
    url: image.url ?? null,
    badge: image.ref != null && !willBeUsed.has(image.ref) ? "removed" : null,
  }));

  return {
    before,
    after,
    changed: (stagePlan?.changes ?? []).some((c) => c.kind === "media"),
  };
}

function impactsFor(
  colours: ColoursBlock | null,
  title: TitleBlock | null,
  description: DescriptionBlock | null,
  price: PriceBlock | null,
  tags: TagsBlock | null,
  materials: MaterialsBlock | null,
  images: ImagesBlock | null,
): ImpactTag[] {
  // Reading order (decision 3's gallery-first order), not emission order.
  const impacts: ImpactTag[] = [];
  if (images?.changed) impacts.push("Images");
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
  const tags = buildTags(etsyListingPlan);
  const materials = buildMaterials(etsyListingPlan);
  const colours = buildColours(productPlan);
  const price = buildPrice(productPlan);
  const images = buildImages(etsyMediaPlan);

  return {
    impacts: impactsFor(colours, title, description, price, tags, materials, images),
    hasEtsyListing: plan.etsy_listing_id !== null,
    title,
    description,
    tags,
    materials,
    colours,
    price,
    images,
    priceRows: buildPriceRows(productPlan, belowCost),
    belowCost,
  };
}
