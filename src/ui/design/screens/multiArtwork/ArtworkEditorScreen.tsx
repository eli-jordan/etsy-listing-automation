import "./fakeApi";
import { useState } from "react";
import { EditableName } from "../../../src/components/EditableName";
import { EditorHead } from "../../../src/pages/ListingEditorPage";
import { IssuesBanner } from "../../../src/pages/editor/IssuesBanner";
import { metaFor } from "../../../src/pages/editor/saveMeta";
import type { ListingDetail } from "../../../src/types";
import { artworkIssues, type Base, type Colour, type Design, type Tone } from "./artwork";
import { ArtworkStrip, type SlotTarget } from "./ArtworkStrip";
import { ArtworkPicker, BackToOneDialog } from "./Pickers";
import { VariantsArtworkTab } from "./VariantsArtworkTab";
import "./multiArtwork.css";

/** What a picker is choosing a file for. */
export type PickTarget = { kind: "one" } | { kind: "slot"; tone: Tone } | { kind: "colour"; name: string };

export interface ArtworkEditorProps {
  /** The listing's directory name, as the real head shows it. */
  name: string;
  profile: string;
  sizes: string[];
  library: Design[];
  base: Base;
  colours: Colour[];
  previewed: string;
  /** Fake listing ids, so the head's real "Open on" menu has something to open. */
  etsyListingId: number | null;
  printifyProductId: string | null;
  /** Open on arrival, so a frame can show the picker, the dialog or a panel. */
  picking?: PickTarget | null;
  leaving?: boolean;
  recentOpen?: SlotTarget | null;
}

const TABS = [
  { id: "variants", label: "Variants" },
  { id: "pricing", label: "Pricing" },
  { id: "images", label: "Listing Images" },
  { id: "details", label: "Listing Details" },
] as const;

/** Saved a couple of minutes before the frame loads -- the real `SavedAgo`
 * renders the relative time. */
const SAVED_AT = Date.now() - 2 * 60 * 1000;

/**
 * The listing editor with the artwork map editable (docs/multi-artwork-ui.md).
 * The page head, issues banner and tab strip are the app's own components and
 * markup, fed fake data; the design strip and the Variants tab are the new
 * design (a linked light/dark pair, per-colour designs).
 */
export function ArtworkEditorScreen(props: ArtworkEditorProps) {
  const [base, setBase] = useState<Base>(props.base);
  const [colours, setColours] = useState<Colour[]>(props.colours);
  const [previewed, setPreviewed] = useState(props.previewed);
  const [picking, setPicking] = useState<PickTarget | null>(props.picking ?? null);
  const [leaving, setLeaving] = useState(props.leaving ?? false);
  const [recent, setRecent] = useState<SlotTarget | null>(props.recentOpen ?? null);

  const issues = artworkIssues(base, colours, props.profile);
  const detail = {
    name: props.name,
    status: "live",
    etsy_listing_id: props.etsyListingId,
    printify_product_id: props.printifyProductId,
    issues,
  } as unknown as ListingDetail;

  function link() {
    if (base.mode === "one") return;
    const kept = [base.light, base.dark].filter((d): d is Design => d !== null);
    const distinct = kept.filter((d, i) => kept.findIndex((k) => k.file === d.file) === i);
    // Nothing to choose between: link without asking.
    if (distinct.length <= 1) setBase({ mode: "one", design: distinct[0] ?? null });
    else setLeaving(true);
  }

  function unlink() {
    if (base.mode === "light-dark") return;
    setBase({ mode: "light-dark", light: base.design, dark: base.design });
  }

  function pick(target: PickTarget, design: Design) {
    if (target.kind === "one") setBase({ mode: "one", design });
    // A slot picked while linked splits the pair; the other keeps the file it had.
    if (target.kind === "slot")
      setBase(
        base.mode === "light-dark"
          ? { ...base, [target.tone]: design }
          : { mode: "light-dark", light: base.design, dark: base.design, [target.tone]: design },
      );
    if (target.kind === "colour") {
      setColours((cs) => cs.map((c) => (c.name === target.name ? { ...c, own: design } : c)));
      setPreviewed(target.name);
    }
    setPicking(null);
  }

  // Turning a colour off drops its own design with it.
  const setEnabled = (keep: (c: Colour) => boolean) =>
    setColours((cs) => cs.map((c) => ({ ...c, enabled: keep(c), own: keep(c) ? c.own : null })));

  const badge = issues.filter((i) => i.severity !== "info").length;

  return (
    <div className="editor">
      <EditorHead
        detail={detail}
        onBack={() => {}}
        flush={async () => {}}
        title={<EditableName value={props.name} onCommit={() => {}} />}
        meta={metaFor({ kind: "saved", savedAt: SAVED_AT }, props.name)}
      />

      <IssuesBanner issues={issues} activeTab="variants" onJumpTo={() => {}} />

      <ArtworkStrip
        base={base}
        colours={colours}
        library={props.library}
        open={recent}
        setOpen={setRecent}
        onLink={link}
        onUnlink={unlink}
        onPick={pick}
        onFind={setPicking}
        onPreview={setPreviewed}
      />

      <div className="tabs seg">
        {TABS.map((t) => (
          <div key={t.id} className={t.id === "variants" ? "seg-opt seg-opt--on" : "seg-opt"}>
            {t.label}
            {t.id === "variants" && badge > 0 && <span className="tab-badge tab-badge--warn">{badge}</span>}
          </div>
        ))}
      </div>

      <VariantsArtworkTab
        profile={props.profile}
        sizes={props.sizes}
        colours={colours}
        base={base}
        previewed={previewed}
        status=""
        onPreview={setPreviewed}
        onToggle={(name) => setEnabled((c) => (c.name === name ? !c.enabled : c.enabled))}
        onOnlyShade={(tone) => setEnabled((c) => c.tone === tone)}
        onPickColour={(name) => {
          setPreviewed(name);
          setPicking({ kind: "colour", name });
        }}
        onPickSlot={(tone) => {
          setRecent({ kind: "slot", tone });
          window.scrollTo({ top: 0, behavior: "smooth" });
        }}
        onAutomatic={(name) => setColours((cs) => cs.map((c) => (c.name === name ? { ...c, own: null } : c)))}
      />

      {picking !== null && (
        <ArtworkPicker
          target={picking}
          base={base}
          colours={colours}
          library={props.library}
          onPick={(d) => pick(picking, d)}
          onClose={() => setPicking(null)}
        />
      )}

      {leaving && base.mode === "light-dark" && (
        <BackToOneDialog
          base={base}
          colours={colours}
          onKeep={(design) => {
            setBase({ mode: "one", design });
            setLeaving(false);
          }}
          onCancel={() => setLeaving(false)}
        />
      )}
    </div>
  );
}
