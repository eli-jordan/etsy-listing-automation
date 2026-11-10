// A plan the shipped Callouts and ComparisonView can read, for the built frame:
// a wording edit, a real description edit and a setting Printify re-attached.
import type { PlanDTO } from "../../../src/types";
import { colours, description, etsyListingId, materials, tags, title } from "./_fixtures";
import { afterRefs, beforeRefs } from "./_tiles";

const editedDescription = description.after.replace("within 14 days", "within 30 days");

const facts = (titleText: string, descriptionText: string, shipping: string) => ({
  title: titleText,
  description: descriptionText,
  tags,
  materials,
  shop_section: null,
  shipping_profile: shipping,
});

const prices = colours.map((colour) => ({ colour, size: "M", price: "336 NOK" }));

export const builtPlan = {
  listing: "nan-dont-count-on-it",
  is_live: true,
  etsy_listing_id: etsyListingId,
  stage_plans: [
    {
      stage: "printify_product",
      drift: [],
      snapshot: { live: prices, desired: prices },
      outcome: { type: "no_work", reason: "No changes" },
    },
    {
      stage: "etsy_listing",
      snapshot: {
        live: facts(title.live, editedDescription, "Printify default"),
        desired: facts(title.after, description.after, "Norway standard"),
      },
      drift: [
        { path: "title", last_applied: title.lastApplied, live: title.live },
        { path: "description", last_applied: description.after, live: editedDescription },
        {
          path: "shipping_profile_id",
          last_applied: 1,
          live: 2,
          last_applied_label: "Norway standard",
          live_label: "Printify default",
        },
      ],
      outcome: {
        type: "work",
        reason: "Etsy disagrees with what was last applied -- re-asserting",
        changes: [],
        actions: [],
      },
    },
    {
      stage: "etsy_media",
      drift: [],
      snapshot: {
        live: beforeRefs.map((ref, index) => ({
          rank: index + 1,
          ref: ref.ref,
          image_id: index,
          url: ref.src,
        })),
        desired: afterRefs.map((ref, index) => ({ rank: index + 1, ref, file: `${ref}.png` })),
      },
      outcome: {
        type: "work",
        reason: "the media manifest changed",
        changes: [{ kind: "media", rank: 1, before: "black", after: "ivory" }],
        actions: [],
      },
    },
  ],
} as unknown as PlanDTO;
