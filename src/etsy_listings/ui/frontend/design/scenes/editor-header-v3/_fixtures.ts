import type { Issue, ListingStatus } from "../../../src/types";

export interface HeaderListing {
  name: string;
  status: ListingStatus;
  path: string;
  savedAgo: string;
  design: { name: string; file: string };
  etsyListingId: number | null;
  printifyProductId: string | null;
  issues: Issue[];
}

/** What the editor knows when it was opened from a batch summary
 * (`?batch=`, `GET /api/listings/{name}/batch`). */
export interface BatchContext {
  label: string;
  reviewed: boolean;
}

export const batch: BatchContext = { label: "Developer tees", reviewed: false };

/** The listing from the screenshot that prompted this exploration. */
export const listing: HeaderListing = {
  name: "duke-java-developer",
  status: "draft",
  path: "listings/duke-java-developer/listing.yaml",
  savedAgo: "Saved 3 mins ago",
  design: { name: "duke-java-developer", file: "designs/duke-java-developer.png" },
  etsyListingId: 1841237765,
  printifyProductId: "66f1c2a9e4b0d73a1c0e5b12",
  issues: [
    {
      severity: "block",
      tab: "details",
      where: "Listing Details › Description",
      message:
        "etsy.description.lead is empty. The lead is the opening paragraph a shopper reads, and deployment is blocked until it is set.",
    },
  ],
};
