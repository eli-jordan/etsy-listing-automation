// The listing editor on its Listing Images tab, with the template-finding part
// pluggable: every frame here is the same page, and only that part differs.
import type { ReactNode } from "react";
import { useState } from "react";
import { EditableName } from "../../../src/components/EditableName";
import { EditorHead } from "../../../src/pages/ListingEditorPage";
import { metaFor } from "../../../src/pages/editor/saveMeta";
import type { ListingDetail } from "../../../src/types";
import { COLOURS, type Entry, initialMedia, LISTING, type PickerTemplate, templates } from "./_fixtures";
import "./_filter.css";

const TABS = ["Variants", "Pricing", "Listing Images", "Listing Details"];
const SAVED_AT = Date.now() - 2 * 60 * 1000;

export interface Picker {
  media: Entry[];
  focus: string;
  setFocus: (template: string) => void;
  toggle: (template: string, colour: string) => void;
  addMissing: (template: string) => void;
  inCount: (template: string) => number;
}

export function usePicker(initialFocus: string): Picker {
  const [media, setMedia] = useState(initialMedia);
  const [focus, setFocus] = useState(initialFocus);
  const held = (template: string, colour: string) =>
    media.some((m) => m.template === template && m.colour === colour);
  return {
    media,
    focus,
    setFocus,
    toggle: (template, colour) =>
      setMedia((current) =>
        held(template, colour)
          ? current.filter((m) => !(m.template === template && m.colour === colour))
          : [...current, { template, colour }],
      ),
    addMissing: (template) =>
      setMedia((current) => [
        ...current,
        ...COLOURS.filter((colour) => !held(template, colour)).map((colour) => ({ template, colour })),
      ]),
    inCount: (template) => media.filter((m) => m.template === template).length,
  };
}

/** The colour chips and add-all, as the app's template row offers them. */
export function ColourChoices({ template, picker }: { template: string; picker: Picker }) {
  const missing = COLOURS.filter(
    (colour) => !picker.media.some((m) => m.template === template && m.colour === colour),
  );
  return (
    <>
      <div className="cchips">
        {COLOURS.map((colour) => {
          const on = !missing.includes(colour);
          return (
            <button
              key={colour}
              type="button"
              className={on ? "cchip cchip--in" : "cchip"}
              aria-pressed={on}
              onClick={() => picker.toggle(template, colour)}
            >
              {colour}
            </button>
          );
        })}
      </div>
      {missing.length > 1 && (
        <button
          type="button"
          className="btn-like btn-like--ghost btn-sm"
          onClick={() => picker.addMissing(template)}
        >
          + Add all {missing.length} remaining colours
        </button>
      )}
    </>
  );
}

/** One template in the locator: the app's row, plus a line for its tags. */
export function TemplateRow({
  template,
  picker,
  open,
  onToggleOpen,
}: {
  template: PickerTemplate;
  picker: Picker;
  open: boolean;
  onToggleOpen: () => void;
}) {
  const count = picker.inCount(template.name);
  return (
    <div className={open ? "loc-tmpl loc-tmpl--open" : "loc-tmpl"}>
      <div
        className="loc-tmpl__head"
        onClick={onToggleOpen}
        onMouseEnter={() => picker.setFocus(template.name)}
      >
        <span className="loc-tmpl__mini">
          <img src={template.src} alt="" />
        </span>
        <span className="loc-tmpl__text">
          <span className="loc-tmpl__name">{template.name}</span>
          <span className={`lf-tags${template.tags.length ? "" : " lf-tags--none"}`}>
            {template.tags.length ? template.tags.join(" · ") : "No labels"}
          </span>
        </span>
        {count > 0 && <span className="loc-tmpl__count">{count} in listing</span>}
        <span className="loc-tmpl__caret" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
      </div>
      {open && (
        <div className="loc-tmpl__body">
          <ColourChoices template={template.name} picker={picker} />
        </div>
      )}
    </div>
  );
}

/** The locator's frame and mode switch, around each direction's own content. */
export function LocatorShell({ children }: { children: ReactNode }) {
  return (
    <div className="locator lf-locator">
      <div className="locator__head">
        <span className="locator__title">Add media</span>
        <span className="locator__hint">Hover to preview · click to add</span>
      </div>
      <div className="seg locator__modes">
        <button type="button" className="seg-opt seg-opt--on" aria-pressed="true">
          Mockup templates
        </button>
        <button type="button" className="seg-opt" aria-pressed="false">
          Files
        </button>
      </div>
      {children}
    </div>
  );
}

export function ImagesScreen({
  picker,
  locator,
  overlay,
}: {
  picker: Picker;
  locator: ReactNode;
  overlay?: ReactNode;
}) {
  const detail = {
    name: LISTING,
    status: "draft",
    etsy_listing_id: null,
    printify_product_id: null,
    issues: [],
  } as unknown as ListingDetail;
  const focused = templates.find((t) => t.name === picker.focus) ?? templates[0]!;

  return (
    <div className="editor">
      <EditorHead
        detail={detail}
        onBack={() => {}}
        flush={async () => {}}
        title={<EditableName value={LISTING} onCommit={() => {}} />}
        meta={metaFor({ kind: "saved", savedAt: SAVED_AT }, LISTING)}
      />
      <div className="tabs seg">
        {TABS.map((tab) => (
          <div key={tab} className={tab === "Listing Images" ? "seg-opt seg-opt--on" : "seg-opt"}>
            {tab}
          </div>
        ))}
      </div>

      <div className="images-tab">
        {locator}
        <div className="images-right">
          <div className="preview-pane lf-preview">
            <img src={focused.src} alt={focused.name} />
            <span className="lf-preview__name">{focused.name}</span>
          </div>
          <div className="reel">
            <div className="reel__head">
              <span className="reel__title">Listing gallery</span>
              <span className="reel__count">{picker.media.length} of 20 images</span>
              <span className="reel__count">0 of 2 videos</span>
            </div>
            <div className="reel__track">
              {picker.media.map((entry) => (
                <div key={`${entry.template}-${entry.colour}`} className="rtile">
                  <div className="rtile__face">
                    <img
                      src={templates.find((t) => t.name === entry.template)?.src}
                      alt={entry.template}
                    />
                  </div>
                  <span className="rtile__label">
                    {entry.template} · {entry.colour}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      {overlay}
    </div>
  );
}
