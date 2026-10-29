import { CircleNotchIcon } from "@phosphor-icons/react/dist/csr/CircleNotch";
import { UploadSimpleIcon } from "@phosphor-icons/react/dist/csr/UploadSimple";
import { useRef, useState, type DragEvent, type ReactNode } from "react";
import type { StripApi } from "../../screens/multiArtwork/ArtworkEditorScreen";
import type { SlotTarget } from "../../screens/multiArtwork/ArtworkStrip";
import { TILE, toneLabel, type Base, type Design, type Tone } from "../../screens/multiArtwork/artwork";
import "./_strips.css";

export type { StripApi, SlotTarget };
export type Key = "one" | Tone;

/** What a frame can open on, so the static canvas shows each state. */
export interface StripStart {
  /** A file is being held over this target. */
  dragging?: Key | "card";
  /** This target is mid-upload. */
  uploading?: { key: Key; name: string };
}

export const ONE: SlotTarget = { kind: "one" };
export const slotOf = (tone: Tone): SlotTarget => ({ kind: "slot", tone });
export const keyOf = (t: SlotTarget): Key => (t.kind === "one" ? "one" : t.tone);
export const targetOf = (k: Key): SlotTarget => (k === "one" ? ONE : slotOf(k));
export const keyLabel = (k: Key) => (k === "one" ? "all shirts" : toneLabel(k));

export function current(base: Base, k: Key): Design | null {
  if (k === "one") return base.mode === "one" ? base.design : null;
  return base.mode === "light-dark" ? base[k] : base.design;
}

/** Light half, dark half: the cloth behind a design that prints on both. */
export const BOTH = `linear-gradient(135deg, ${TILE.light} 0 50%, ${TILE.dark} 50% 100%)`;
export const tileFor = (k: Key) => (k === "one" ? BOTH : TILE[k]);

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer.types).includes("Files");

/** Drag-and-drop for one target. Counts enter/leave so moving over a child
 * doesn't flicker the highlight off. */
export function useDrop(onFile: (f: File) => void, initial = false) {
  const [over, setOver] = useState(initial);
  const depth = useRef(0);
  return {
    over,
    props: {
      onDragEnter: (e: DragEvent) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        depth.current += 1;
        setOver(true);
      },
      onDragOver: (e: DragEvent) => {
        if (hasFiles(e)) e.preventDefault();
      },
      onDragLeave: () => {
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setOver(false);
      },
      onDrop: (e: DragEvent) => {
        e.preventDefault();
        depth.current = 0;
        setOver(false);
        const file = e.dataTransfer.files[0];
        if (file) onFile(file);
      },
    },
  };
}

/** Upload progress per target, wrapped around the screen's fake upload. */
export function useUploads(api: StripApi, start?: StripStart["uploading"]) {
  const [uploading, setUploading] = useState<Partial<Record<Key, string>>>(
    start ? { [start.key]: start.name } : {},
  );
  async function upload(k: Key, file: File) {
    setUploading((u) => ({ ...u, [k]: file.name }));
    try {
      await api.onUpload(targetOf(k), file);
    } finally {
      setUploading((u) => ({ ...u, [k]: undefined }));
    }
  }
  return { uploading, upload };
}

/** A design on the cloth it prints on; spins while a file uploads into it. */
export function Thumb({
  design,
  tile,
  size = 52,
  busy = false,
}: {
  design: Design | null;
  tile: string;
  size?: number;
  busy?: boolean;
}) {
  return (
    <span
      className={design === null && !busy ? "ds-thumb ds-thumb--empty" : "ds-thumb"}
      style={{ width: size, height: size, background: design === null && !busy ? undefined : tile }}
    >
      {busy ? (
        <CircleNotchIcon className="ds-spin" weight="bold" aria-label="Uploading" />
      ) : (
        design !== null && <img src={design.url} alt="" />
      )}
    </span>
  );
}

/** The highlight laid over a target while a file is held above it. */
export function DropVeil({ children }: { children: ReactNode }) {
  return (
    <div className="ds-veil" aria-hidden="true">
      <UploadSimpleIcon weight="bold" />
      <span>{children}</span>
    </div>
  );
}

/** A visually plain "browse" fallback for people who don't drag. */
export function Browse({
  onFile,
  className = "ds-textbtn",
  children = "Upload a file…",
}: {
  onFile: (f: File) => void;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <label className={className}>
      {children}
      <input
        type="file"
        accept="image/png,image/svg+xml,image/jpeg"
        hidden
        onChange={(e) => {
          const f = e.currentTarget.files?.[0];
          if (f) onFile(f);
          e.currentTarget.value = "";
        }}
      />
    </label>
  );
}

/** Recent designs as thumbnails, plus the full list and an upload. */
export function RecentPanel({
  api,
  k,
  onDone,
  onFile,
}: {
  api: StripApi;
  k: Key;
  onDone: () => void;
  onFile: (f: File) => void;
}) {
  const now = current(api.base, k);
  return (
    <div className="ds-recent">
      <div className="ds-recent__head">
        <span className="section-label">Recent designs for {keyLabel(k)}</span>
        <span className="ds-recent__hint">or drop a file anywhere on the selector</span>
      </div>
      <div className="ds-recent__grid">
        {api.library.slice(0, 5).map((d) => (
          <button
            key={d.file}
            type="button"
            className={now?.file === d.file ? "ds-pick ds-pick--on" : "ds-pick"}
            onClick={() => {
              api.onPick(targetOf(k), d);
              onDone();
            }}
          >
            <Thumb design={d} tile={tileFor(k)} size={56} />
            <span className="ds-pick__name">{d.name}</span>
          </button>
        ))}
      </div>
      <div className="ds-recent__foot">
        <button
          type="button"
          className="btn-like btn-like--ghost btn-sm"
          onClick={() => {
            api.onFind(targetOf(k));
            onDone();
          }}
        >
          Find a design…
        </button>
        <Browse
          className="btn-like btn-like--ghost btn-sm"
          onFile={(f) => {
            onDone();
            onFile(f);
          }}
        />
      </div>
    </div>
  );
}

/** "Prints on …" for a key, in the strip's own words. */
export function printsOn(api: StripApi, k: Key): string {
  const enabled = api.colours.filter((c) => c.enabled && c.own === null);
  if (k === "one") return "Prints on every colour you sell";
  const names = enabled.filter((c) => c.tone === k).map((c) => c.name[0].toUpperCase() + c.name.slice(1));
  if (names.length === 0) return "No colour you sell needs it";
  return `Prints on ${names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : names[0]}`;
}
