import "../../screens/multiArtwork/fakeApi";
import type { ReactNode } from "react";
import { EditableName } from "../../../src/components/EditableName";
import { EditorHead } from "../../../src/pages/ListingEditorPage";
import { IssuesBanner } from "../../../src/pages/editor/IssuesBanner";
import { metaFor } from "../../../src/pages/editor/saveMeta";
import type { Issue, ListingDetail } from "../../../src/types";
import { locator, reel as defaultReel, type ReelItem } from "./_fixtures";
import "./_positions.css";

const TABS = [
  { id: "variants", label: "Variants" },
  { id: "pricing", label: "Pricing" },
  { id: "images", label: "Listing Images" },
  { id: "details", label: "Listing Details" },
] as const;

const SAVED_AT = Date.now() - 2 * 60 * 1000;
const NAME = "night-hike-club";

interface Props {
  /** The preview pane: stage + foot. */
  pane: ReactNode;
  issues?: Issue[];
  selected?: number | null;
  reel?: ReelItem[];
}

/**
 * The listing editor on its Listing Images tab. Head, issues banner and tabs
 * are the app's own components; the locator and reel copy the app's markup
 * and classes with fixture photos (their real versions read thumbnails from
 * the server). Only the preview pane is new design.
 */
export function EditorFrame({ pane, issues = [], selected = 0, reel = defaultReel }: Props) {
  const detail = {
    name: NAME,
    status: "live",
    etsy_listing_id: 1784230917,
    printify_product_id: "66f2a1c9e8b7d40012ab34cd",
    issues,
  } as unknown as ListingDetail;
  const badge = issues.filter((i) => i.tab === "images" && i.severity !== "info").length;

  return (
    <div className="editor">
      <EditorHead
        detail={detail}
        onBack={() => {}}
        flush={async () => {}}
        title={<EditableName value={NAME} onCommit={() => {}} />}
        meta={metaFor({ kind: "saved", savedAt: SAVED_AT }, NAME)}
      />
      <IssuesBanner issues={issues} activeTab="images" onJumpTo={() => {}} />
      <div className="tabs seg">
        {TABS.map((t) => (
          <div key={t.id} className={t.id === "images" ? "seg-opt seg-opt--on" : "seg-opt"}>
            {t.label}
            {t.id === "images" && badge > 0 && <span className="tab-badge tab-badge--warn">{badge}</span>}
          </div>
        ))}
      </div>

      <div className="images-tab">
        <Locator />
        <div className="images-right">
          <div className="preview-pane">{pane}</div>
          <Reel items={reel} selected={selected} />
        </div>
      </div>
    </div>
  );
}

function Locator() {
  return (
    <div className="locator">
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
      <div className="locator__list">
        {locator.map((t) => (
          <div key={t.name} className={t.open ? "loc-tmpl loc-tmpl--open" : "loc-tmpl"}>
            <div className="loc-tmpl__head">
              <span className="loc-tmpl__mini">
                <img src={t.photo} alt="" />
              </span>
              <span className="loc-tmpl__text">
                <span className="loc-tmpl__name">{t.name}</span>
                <span className="loc-tmpl__kind">{t.kind}</span>
              </span>
              {t.inCount > 0 && <span className="loc-tmpl__count">{t.inCount} in listing</span>}
              <span className="loc-tmpl__caret" aria-hidden="true">
                ▾
              </span>
            </div>
            {t.open && t.colours && (
              <div className="loc-tmpl__body">
                <div className="cchips">
                  {t.colours.map((c) => (
                    <button key={c.name} type="button" className={c.in ? "cchip cchip--in" : "cchip"} aria-pressed={c.in}>
                      {c.name}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function Reel({ items, selected }: { items: ReelItem[]; selected: number | null }) {
  return (
    <div className="reel">
      <div className="reel__head">
        <span className="reel__title">Listing gallery</span>
        <span className="reel__count">{items.length} of 20 images</span>
        <span className="reel__count">0 of 2 videos</span>
        <span className="reel__hint">Drag a tile to change the order Etsy shows them in</span>
      </div>
      <div className="reel__track">
        {items.map((item, i) => (
          <div key={item.label} className={i === selected ? "rtile rtile--selected" : "rtile"}>
            <div className="rtile__face">
              <img src={item.photo} alt={item.label} />
              <span className="rtile__pos">{i + 1}</span>
              {item.positioned && (
                <span className="tp-tile-badge" title="This listing positions the design on this template">
                  <PositionGlyph />
                </span>
              )}
            </div>
            <span className="rtile__label">{item.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Four-way move arrows: the app's icon stroke, drawn inline. */
export function PositionGlyph({ size = 12 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3" />
    </svg>
  );
}
