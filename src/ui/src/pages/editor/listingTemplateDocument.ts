import {
  createListingTemplate,
  putListingTemplate,
  renameListingTemplate,
} from "../../api/listingTemplates";
import type { AutosaveTransport, SaveOutcome } from "../../hooks/useAutosave";
import type {
  ListingDetail,
  ListingTemplateDetail,
  ListingTemplateSaveResult,
  ListingTemplateSource,
} from "../../types";

/**
 * A listing template as the listing editor's tabs read it, and back.
 *
 * The listing-template editor mounts the listing editor's own tabs (UI doc
 * §3), and they read a `ListingDetail`. A listing template is not a listing
 *, so this is the one place the two shapes meet: the design-specific
 * fields a template does not have are filled with a listing's empty values on
 * the way in -- no design, brief, title, tags or lead -- and are dropped on the
 * way out, along with everything the server computes. What the editor shows
 * as the preview design is never in either direction: it lives in the
 * shell's state, not the document (UI doc §3, "It is not saved with the
 * template").
 */

export function templateAsListing(template: ListingTemplateDetail): ListingDetail {
  const etsy = template.etsy;
  return {
    name: template.name,
    modified_at: template.modified_at,
    garment_profile: template.garment_profile,
    colors: template.colors,
    prices: template.prices,
    pricing_plan: template.pricing_plan ?? null,
    price_overrides: template.price_overrides,
    media: template.media,
    design: {},
    brief: "",
    etsy: {
      title: "",
      tags: [],
      description: {
        lead: "",
        text: etsy.description.text ?? null,
        ref: etsy.description.ref ?? null,
      },
      renewal: etsy.renewal ?? null,
      section: etsy.section ?? null,
      shipping_profile: etsy.shipping_profile ?? null,
      variation_images: etsy.variation_images ?? null,
    },
    status: "draft",
    issues: template.issues,
    field_errors: {},
    pricing_plan_name: template.pricing_plan_name ?? null,
    resolved_prices: template.resolved_prices,
    garment_materials: template.garment_materials ?? null,
    garment_product_type: template.garment_product_type ?? null,
    garment_brand: template.garment_brand ?? null,
    garment_model: template.garment_model ?? null,
    gestures: [],
    description_composed: template.description_composed,
  };
}

/** The fields of the editor's `ListingDetail` that are `template.yaml`:
 * `config/listing_template.py`'s `ListingTemplate`, which forbids every
 * other field. Listed positively, as `listingDocument` is, so a new computed
 * field can never start being written. */
export function listingTemplateDocument(detail: ListingDetail): Record<string, unknown> {
  const etsy = detail.etsy;
  return {
    garment_profile: detail.garment_profile,
    colors: detail.colors,
    prices: detail.prices,
    pricing_plan: detail.pricing_plan ?? null,
    price_overrides: detail.price_overrides,
    media: detail.media,
    etsy: {
      description: { text: etsy.description.text ?? null, ref: etsy.description.ref ?? null },
      renewal: etsy.renewal ?? null,
      section: etsy.section ?? null,
      shipping_profile: etsy.shipping_profile ?? null,
      variation_images: etsy.variation_images ?? null,
    },
  };
}

function outcome(result: ListingTemplateSaveResult): SaveOutcome {
  if (result.saved && result.template) {
    return { saved: true, detail: templateAsListing(result.template) };
  }
  return { saved: false, issues: result.issues, field_errors: result.field_errors ?? {} };
}

/** `useAutosave`'s transport for a listing template: valid-only
 * `PUT` of the whole document, the create that naming the draft is (from
 * `source`, carrying the edits made before it), and the rename. There is no
 * describing an unnamed one -- its issues are the draft's until it is
 * named. Build it once per source: the hook needs it stable. */
export function listingTemplateTransport(source: ListingTemplateSource | null): AutosaveTransport {
  return {
    document: listingTemplateDocument,
    describe: null,
    create: async (name, candidate) => {
      if (source === null) throw new Error("a listing template is only created from a source");
      return outcome(await createListingTemplate(name, source, candidate));
    },
    save: async (name, _patch, candidate) => outcome(await putListingTemplate(name, candidate)),
    rename: async (from, to) => templateAsListing(await renameListingTemplate(from, to)),
  };
}
