import mockupBlack from "../../assets/batch-deploy/mockup-black.png";
import mockupIvory from "../../assets/batch-deploy/mockup-ivory.png";
import mockupLifestyle from "../../assets/batch-deploy/mockup-lifestyle.png";
import mockupMoss from "../../assets/batch-deploy/mockup-moss.png";

export interface ListingTemplateFixture {
  name: string;
  garment: string;
  colours: number;
  pricing: string;
  gallery: string[];
  batches: number;
}

export const listingTemplates: ListingTemplateFixture[] = [
  {
    name: "heavyweight-tee",
    garment: "Comfort Colors 1717",
    colours: 5,
    pricing: "Standard NOK",
    gallery: [mockupLifestyle, mockupBlack, mockupIvory, mockupMoss],
    batches: 2,
  },
  {
    name: "everyday-tee",
    garment: "Bella + Canvas 3001",
    colours: 4,
    pricing: "Standard NOK",
    gallery: [mockupIvory, mockupMoss, mockupBlack],
    batches: 1,
  },
  {
    name: "trail-hoodie",
    garment: "Gildan 18500",
    colours: 3,
    pricing: "Hoodie NOK",
    gallery: [mockupMoss, mockupLifestyle],
    batches: 0,
  },
];

export const batchLabel = "heavyweight-tee · 27 Sep 11:42";

/** Where a batch is in its life. Derived, never stored:
 *  staging   - uploaded, not confirmed; nothing created yet
 *  drafting  - listings created, AI queue still has work
 *  in-review - drafting finished, not every listing marked reviewed
 *  complete  - every created listing marked reviewed
 *  stopped   - Cancel batch left work undrafted; Resume from the summary */
export type BatchStatus = "staging" | "drafting" | "in-review" | "complete" | "stopped";

export interface RecentBatchFixture {
  label: string;
  template: string;
  created: string;
  status: BatchStatus;
  progress: string;
  /** Failures ride along as a count; they never replace the status. */
  attention?: string;
}

export const recentBatches: RecentBatchFixture[] = [
  {
    label: "everyday-tee · 26 Sep 16:05",
    template: "everyday-tee",
    created: "Yesterday",
    status: "staging",
    progress: "9 designs, not created yet · kept until 3 Oct",
  },
  {
    label: batchLabel,
    template: "heavyweight-tee",
    created: "Today 11:42",
    status: "drafting",
    progress: "5 of 9 drafted · 2 of 9 reviewed",
    attention: "2 need retry",
  },
  {
    label: "Autumn trail drop",
    template: "heavyweight-tee",
    created: "12 Sep",
    status: "in-review",
    progress: "5 of 8 reviewed",
    attention: "1 needs retry",
  },
  {
    label: "Spring restock",
    template: "heavyweight-tee",
    created: "2 Sep",
    status: "stopped",
    progress: "Cancelled with 3 left to draft · 1 of 6 reviewed",
  },
  {
    label: "everyday-tee · 19 Sep 09:10",
    template: "everyday-tee",
    created: "19 Sep",
    status: "complete",
    progress: "6 of 6 reviewed",
  },
];

/** Staging rows: `kind` drives the Check column. */
export type StagingKind = "ok" | "suffixed" | "reused" | "collapsed" | "invalid";

export interface StagingRowFixture {
  source: string;
  name: string;
  kind: StagingKind;
  note?: string;
  error?: string;
}

export const stagingRows: StagingRowFixture[] = [
  { source: "Night Hike Club.png", name: "night-hike-club", kind: "ok" },
  { source: "exports/Mountain Sunrise (1).png", name: "mountain-sunrise-1", kind: "ok" },
  {
    source: "after_rain_trail.png",
    name: "after-rain-trail-2",
    kind: "suffixed",
    note: "after-rain-trail is taken, so -2 was added",
  },
  {
    source: "fjord-mornings-final.png",
    name: "fjord-mornings-final",
    kind: "reused",
    note: "Same image as designs/fjord-mornings.png. The listing reuses that file",
  },
  {
    source: "cedar-trail.png",
    name: "cedar-trail",
    kind: "collapsed",
    note: "2 identical files, staged once: cedar-trail.png, exports/cedar-trail copy.png",
  },
  { source: "Aurora Switchbacks.png", name: "aurora-switchbacks", kind: "ok" },
  { source: "lake_loop.png", name: "lake-loop", kind: "ok" },
  { source: "pine-ridge-run.png", name: "pine-ridge-run", kind: "ok" },
  { source: "★★★.png", name: "summit-coffee", kind: "ok" },
  { source: "trailhead-sunset.png", name: "trailhead-sunset", kind: "ok" },
  {
    source: "moss and miles.png",
    name: "moss-and-miles-2",
    kind: "suffixed",
    note: "moss-and-miles is taken, so -2 was added",
  },
  {
    source: "sketch-draft.png",
    name: "sketch-draft",
    kind: "invalid",
    error: "No transparent background: the PNG has no alpha channel.",
  },
  {
    source: "tiny-logo.png",
    name: "tiny-logo",
    kind: "invalid",
    error: "1200 × 1400 px is smaller than 90% of the print area (3402 × 4050 px needed).",
  },
];

export const ignoredFiles = ["__MACOSX/._cedar-trail.png", "readme.txt", "preview.jpg"];

export type AiState = "drafted" | "drafting" | "queued" | "failed" | "not-created" | "deleted";

export interface BatchRowFixture {
  name: string;
  ai: AiState;
  step?: string;
  proposal?: "ready" | "stale";
  reviewed?: boolean;
  error?: string;
  queue?: number;
}

export const batchRows: BatchRowFixture[] = [
  { name: "night-hike-club", ai: "drafted", proposal: "ready", reviewed: true },
  { name: "mountain-sunrise-1", ai: "drafted", proposal: "ready", reviewed: true },
  { name: "after-rain-trail-2", ai: "drafted", proposal: "stale" },
  { name: "fjord-mornings-final", ai: "drafted", proposal: "ready" },
  { name: "cedar-trail", ai: "drafted", proposal: "ready" },
  { name: "aurora-switchbacks", ai: "drafting", step: "Researching Etsy market" },
  { name: "lake-loop", ai: "queued", queue: 1 },
  { name: "pine-ridge-run", ai: "queued", queue: 2 },
  {
    name: "summit-coffee",
    ai: "failed",
    error: "Market research failed: Etsy rate limit reached. The brief is saved; Retry reruns research and SEO.",
  },
  {
    name: "trailhead-sunset",
    ai: "not-created",
    error: "Couldn't write designs/trailhead-sunset.png: the disk is full. Free space, then Retry.",
  },
  { name: "moss-and-miles-2", ai: "deleted" },
];
