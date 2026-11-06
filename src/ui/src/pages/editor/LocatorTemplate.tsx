import { templateThumbnailUrl } from "../../api/calibrator";
import { isInMedia, missingColours } from "../../media";
import type { ListingDetail, TemplateSummary } from "../../types";
import type { Focus } from "./focus";

/** One calibrated template in the locator: its head, and when open, how it
 * can join the listing's media. */

interface TemplateActions {
  onToggleTemplate: (template: string, colour: string | null) => void;
  onAddMissingColours: (template: string) => void;
  onToggleSwatchSource: (template: string) => void;
  onFocus: (focus: Focus) => void;
}

function entriesFor(detail: ListingDetail, template: string): number {
  return detail.media.filter((m) => typeof m !== "string" && m.template === template).length;
}

function ColourChip({
  template,
  colour,
  inListing,
  onToggleTemplate,
  onFocus,
}: {
  template: string;
  colour: string;
  inListing: boolean;
} & Pick<TemplateActions, "onToggleTemplate" | "onFocus">) {
  return (
    <button
      type="button"
      className={inListing ? "cchip cchip--in" : "cchip"}
      aria-pressed={inListing}
      onClick={() => onToggleTemplate(template, colour)}
      onMouseEnter={() => onFocus({ kind: "template", template, colour })}
    >
      {colour}
      {inListing && (
        <svg
          className="cchip__tick"
          viewBox="0 0 24 24"
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M5 13l4 4L19 7" />
        </svg>
      )}
    </button>
  );
}

function swatchSubtitle(template: string, swatchTemplate: string | null): string {
  if (swatchTemplate === template) return "Etsy shows these beside each colour option";
  return swatchTemplate ? `Currently using ${swatchTemplate}` : "Off — no swatch images sent";
}

/** How many of the listing's colours the swatch template has a photo for,
 * and which ones Etsy will leave empty. */
function SwatchCoverage({ colours, uncovered }: { colours: number; uncovered: string[] }) {
  if (uncovered.length === 0) {
    return <span className="swatch-status swatch-status--ok">{`All ${colours} covered`}</span>;
  }
  const one = uncovered.length === 1;
  return (
    <>
      <span className="swatch-status swatch-status--warn">
        {`${colours - uncovered.length} of ${colours} covered`}
      </span>
      <p className="swatch-note">
        {uncovered.join(", ")} {one ? "has" : "have"} no image here — Etsy keeps{" "}
        {one ? "that swatch" : "those swatches"} empty.
      </p>
    </>
  );
}

function SwatchSource({
  template,
  swatchTemplate,
  colours,
  missing,
  onToggleSwatchSource,
}: {
  template: string;
  swatchTemplate: string | null;
  colours: number;
  missing: string[];
  onToggleSwatchSource: (template: string) => void;
}) {
  const on = swatchTemplate === template;
  return (
    <div className="tmpl-swatch">
      <div className="tmpl-swatch__row">
        <span className="tmpl-swatch__label" id={`swatch-${template}`}>
          Use for Etsy colour swatches
          <span className="tmpl-swatch__sub">{swatchSubtitle(template, swatchTemplate)}</span>
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-labelledby={`swatch-${template}`}
          className={on ? "switch switch--on" : "switch"}
          onClick={() => onToggleSwatchSource(template)}
        >
          <span className="switch__knob" />
        </button>
      </div>
      {on && <SwatchCoverage colours={colours} uncovered={missing} />}
    </div>
  );
}

function ColourMatrixBody({
  template,
  detail,
  inCount,
  swatchTemplate,
  actions,
}: {
  template: string;
  detail: ListingDetail;
  inCount: number;
  swatchTemplate: string | null;
  actions: TemplateActions;
}) {
  const missing = missingColours(detail.media, detail.colors, template);
  return (
    <>
      <div className="cchips">
        {/* The listing's own colours, not `t.colours`:
            a colour-matrix set's photos are named for
            ADR-0004's slug, but a template with a shared
            filename prefix (`{template}-{colour}.png`)
            reports that whole prefixed stem as its
            "colour" (`template_colours`'s enumeration
            direction has no slug to match against,
            unlike `template_base_image`'s lookup
            direction, which resolves a bare slug against
            exactly this fallback) -- so comparing against
            `detail.colors` by string equality showed
            nothing at all for such a template. `media[]`
            always stores the listing's own bare slug
            (confirmed by `isInMedia`), so that is what a
            chip must offer, regardless of what the
            template's own photos happen to be named. */}
        {detail.colors.map((colour) => (
          <ColourChip
            key={colour}
            template={template}
            colour={colour}
            inListing={isInMedia(detail.media, template, colour)}
            onToggleTemplate={actions.onToggleTemplate}
            onFocus={actions.onFocus}
          />
        ))}
      </div>

      {missing.length > 1 && (
        <button
          type="button"
          className="btn-like btn-like--ghost btn-sm"
          onClick={() => actions.onAddMissingColours(template)}
        >
          + Add all {missing.length} remaining colours
        </button>
      )}
      {detail.colors.length > 0 && missing.length === 0 && (
        <p className="loc-tmpl__note">Every colour this listing sells is already in the reel.</p>
      )}

      {inCount > 0 && (
        <SwatchSource
          template={template}
          swatchTemplate={swatchTemplate}
          colours={detail.colors.length}
          missing={missing}
          onToggleSwatchSource={actions.onToggleSwatchSource}
        />
      )}
    </>
  );
}

function FixedTemplateBody({
  template,
  detail,
  onToggleTemplate,
}: {
  template: TemplateSummary;
  detail: ListingDetail;
  onToggleTemplate: TemplateActions["onToggleTemplate"];
}) {
  const inListing = isInMedia(detail.media, template.name, null);
  return (
    <>
      <p className="loc-tmpl__note">
        {template.kind === "multiple"
          ? "One photo showing several colours at once — it carries no colour of its own."
          : "One fixed photo, the same for every colour."}
      </p>
      <button
        type="button"
        className={
          inListing ? "btn-like btn-like--ghost btn-sm" : "btn-like btn-like--primary btn-sm"
        }
        onClick={() => onToggleTemplate(template.name, null)}
      >
        {inListing ? "Remove from listing" : "+ Add"}
      </button>
    </>
  );
}

function TemplateBody({
  template,
  detail,
  inCount,
  swatchTemplate,
  actions,
}: {
  template: TemplateSummary;
  detail: ListingDetail;
  inCount: number;
  swatchTemplate: string | null;
  actions: TemplateActions;
}) {
  if (template.kind !== "colour-matrix") {
    return (
      <FixedTemplateBody
        template={template}
        detail={detail}
        onToggleTemplate={actions.onToggleTemplate}
      />
    );
  }
  if (detail.colors.length === 0) {
    // Nothing to offer: a colour-matrix entry needs a
    // colour, and every colour it could name comes from
    // the listing's own `colors:`. Adding one anyway would
    // write `{template, colour: null}`, which is a block.
    return <p className="loc-tmpl__note">Pick colours on Variants first.</p>;
  }
  return (
    <ColourMatrixBody
      template={template.name}
      detail={detail}
      inCount={inCount}
      swatchTemplate={swatchTemplate}
      actions={actions}
    />
  );
}

export function LocatorTemplate({
  template,
  detail,
  open,
  onToggleOpen,
  swatchTemplate,
  actions,
}: {
  template: TemplateSummary;
  detail: ListingDetail;
  open: boolean;
  onToggleOpen: () => void;
  swatchTemplate: string | null;
  actions: TemplateActions;
}) {
  const inCount = entriesFor(detail, template.name);
  const focusColour = template.kind === "colour-matrix" ? (detail.colors[0] ?? null) : null;
  return (
    <div className={open ? "loc-tmpl loc-tmpl--open" : "loc-tmpl"}>
      <div
        className="loc-tmpl__head"
        onClick={onToggleOpen}
        onMouseEnter={() =>
          actions.onFocus({ kind: "template", template: template.name, colour: focusColour })
        }
      >
        <span className="loc-tmpl__mini">
          <img src={templateThumbnailUrl(template.name)} alt="" loading="lazy" />
        </span>
        <span className="loc-tmpl__text">
          <span className="loc-tmpl__name">{template.name}</span>
          <span
            className={`loc-tmpl__labels${template.labels.length === 0 ? " loc-tmpl__labels--none" : ""}`}
          >
            {template.labels.length > 0 ? template.labels.join(" · ") : "No labels"}
          </span>
        </span>
        {inCount > 0 && <span className="loc-tmpl__count">{inCount} in listing</span>}
        <span className="loc-tmpl__caret" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
      </div>

      {open && (
        <div className="loc-tmpl__body">
          <TemplateBody
            template={template}
            detail={detail}
            inCount={inCount}
            swatchTemplate={swatchTemplate}
            actions={actions}
          />
        </div>
      )}
    </div>
  );
}
