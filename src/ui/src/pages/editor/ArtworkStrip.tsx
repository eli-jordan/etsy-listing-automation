import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { CircleNotchIcon } from "@phosphor-icons/react/dist/csr/CircleNotch";
import { UploadSimpleIcon } from "@phosphor-icons/react/dist/csr/UploadSimple";
import { useEffect, useRef, useState, type DragEvent } from "react";
import {
  listGarmentProfiles,
  listingDesignThumbnailUrl,
  listListingDesigns,
  uploadListingDesign,
} from "../../api/listings";
import { refName } from "../../media";
import type { DesignMap, ListingDesignSummary } from "../../types";
import { ArtworkPicker } from "./ArtworkPicker";
import {
  cap,
  isLinked,
  linking,
  keepOne,
  listNames,
  pickFor,
  slotFile,
  slotUsers,
  TILE,
  toneLabel,
  unlinked,
  type SlotTarget,
  type Tone,
} from "./artwork";
import { ChooseBaseDialog } from "./ChooseBaseDialog";
import { ShirtThumb } from "./ShirtThumb";

interface Props {
  design: DesignMap;
  colours: readonly string[];
  garmentProfile: string;
  open: SlotTarget | null;
  onOpen: (target: SlotTarget | null) => void;
  onChange: (next: DesignMap) => void;
  onPreview: (colour: string) => void;
}

/** One row of the picker grid. */
const RECENT = 4;

const ONE: SlotTarget = { kind: "one" };

const sameTarget = (a: SlotTarget | null, b: SlotTarget) =>
  a !== null && a.kind === b.kind && (a.kind === "one" || (b.kind === "slot" && a.tone === b.tone));

function targetLabel(target: SlotTarget): string {
  return target.kind === "one" ? "all shirts" : toneLabel(target.tone);
}

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer.types).includes("Files");

/** Counted: `dragenter`/`dragleave` also fire for every child the pointer crosses. */
function useDragDepth(onChange: (holding: boolean) => void) {
  const depth = useRef(0);
  return {
    enter(e: DragEvent): boolean {
      if (!hasFiles(e)) return false;
      e.preventDefault();
      depth.current += 1;
      if (depth.current === 1) onChange(true);
      return true;
    },
    leave() {
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) onChange(false);
    },
    reset() {
      depth.current = 0;
      onChange(false);
    },
  };
}

function tonePrintsOn(users: string[]): string | null {
  return users.length === 0 ? null : `Prints on ${listNames(users)}`;
}

function finderHint(target: SlotTarget, users: ReturnType<typeof slotUsers>): string {
  if (target.kind === "one") return "Every colour prints it, apart from any with their own design.";
  const using = users[target.tone];
  return using.length > 0
    ? `Prints on ${listNames(using)}.`
    : "No colour you sell uses it right now.";
}

export function ArtworkStrip({
  design,
  colours,
  garmentProfile,
  open,
  onOpen,
  onChange,
  onPreview,
}: Props) {
  const [library, setLibrary] = useState<ListingDesignSummary[]>([]);
  const [tones, setTones] = useState<Record<string, Tone>>({});
  const [finding, setFinding] = useState<SlotTarget | null>(null);
  const [choosing, setChoosing] = useState<{ light: string; dark: string } | null>(null);
  const [holding, setHolding] = useState(false);
  const [uploading, setUploading] = useState<{ target: SlotTarget; name: string } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const hold = useDragDepth(setHolding);
  const latest = useRef(design);
  useEffect(() => {
    latest.current = design;
  }, [design]);

  useEffect(() => {
    listListingDesigns()
      .then(setLibrary)
      .catch(() => setLibrary([]));
  }, []);

  useEffect(() => {
    let current = true;
    listGarmentProfiles()
      .then((profiles) => {
        if (current) setTones(profiles.find((p) => p.name === garmentProfile)?.colors ?? {});
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [garmentProfile]);

  const split = !isLinked(design);
  const users = slotUsers(design, colours, tones);
  const own = colours.filter((c) => (design[c] ?? null) !== null);

  function pick(target: SlotTarget, ref: string) {
    onChange(pickFor(design, target, ref));
    onOpen(null);
    setFinding(null);
  }

  async function upload(target: SlotTarget, file: File) {
    setFailed(null);
    setUploading({ target, name: file.name });
    try {
      const added = await uploadListingDesign(file);
      setLibrary((designs) => [added, ...designs.filter((d) => d.file !== added.file)]);
      onChange(pickFor(latest.current, target, added.file));
    } catch (error) {
      const reason = error instanceof Error ? error.message : "the upload failed";
      setFailed(`Couldn't upload ${file.name}: ${reason}`);
    } finally {
      setUploading(null);
    }
  }

  function link() {
    const outcome = linking(design);
    if (outcome.kind === "linked") onChange(outcome.design);
    else setChoosing({ light: outcome.light, dark: outcome.dark });
  }

  const everyShirt =
    own.length > 0
      ? "Prints on every colour without its own design"
      : "Prints on every colour you sell";

  const view = (target: SlotTarget) => {
    const file = slotFile(design, target);
    const tone = target.kind === "slot" ? target.tone : null;
    const used = tone === null ? everyShirt : tonePrintsOn(users[tone]);
    return {
      title: `For ${targetLabel(target)}`,
      target,
      file,
      tones: tone === null ? (["light", "dark"] as const) : [tone],
      usedBy: used,
      open: sameTarget(open, target),
      neededButEmpty: tone !== null && file === null && users[tone].length > 0,
      emptyText: tone === null ? "No design selected" : `Choose the design for ${toneLabel(tone)}`,
      holding,
      uploading: uploading !== null && sameTarget(uploading.target, target) ? uploading.name : null,
    };
  };
  const targets: SlotTarget[] = split
    ? [
        { kind: "slot", tone: "light" },
        { kind: "slot", tone: "dark" },
      ]
    : [ONE];

  return (
    <div className="design-select design-strip">
      {own.length > 0 && (
        <div className="design-select__head">
          <span className="design-select__own">
            Also printing their own design:{" "}
            {own.map((colour, i) => (
              <span key={colour}>
                {i > 0 && ", "}
                <button
                  type="button"
                  className="design-select__colour"
                  onClick={() => onPreview(colour)}
                >
                  {cap(colour)}
                </button>
              </span>
            ))}
          </span>
        </div>
      )}

      <div
        className={
          holding ? "design-strip__card design-strip__card--holding" : "design-strip__card"
        }
        onDragEnter={(e) => hold.enter(e)}
        onDragLeave={() => hold.leave()}
        // A drop nobody takes, the browser opens as a page.
        onDragOver={(e) => {
          if (hasFiles(e)) e.preventDefault();
        }}
        onDrop={(e) => {
          e.preventDefault();
          hold.reset();
        }}
      >
        <div
          className={
            split ? "design-strip__slots design-strip__slots--split" : "design-strip__slots"
          }
        >
          {targets.map((target) => (
            <Slot
              key={target.kind === "one" ? "one" : target.tone}
              {...view(target)}
              onChange={() => onOpen(sameTarget(open, target) ? null : target)}
              onFile={(f) => void upload(target, f)}
            />
          ))}
        </div>
        <div className="design-strip__foot">
          <button
            type="button"
            className="design-strip__mode"
            onClick={() => {
              onOpen(null);
              if (split) link();
              else onChange(unlinked(design));
            }}
          >
            {split
              ? "Use one design for all shirts"
              : "Use different designs on light & dark shirts"}
          </button>
          {failed !== null ? (
            <span className="design-strip__failed" role="alert">
              {failed}
            </span>
          ) : (
            <span className="design-strip__hint">
              <UploadSimpleIcon weight="bold" aria-hidden="true" />
              Drop a PNG on {split ? "a design" : "the design"} to upload it
            </span>
          )}
        </div>
      </div>

      {open !== null && (
        <div className="add-panel">
          <span className="section-label">Recent designs for {targetLabel(open)}</span>
          <div className="template-grid">
            {library.slice(0, RECENT).map((d) => (
              <button
                key={d.file}
                type="button"
                className={
                  slotFile(design, open) === d.file
                    ? "template-card template-card--active"
                    : "template-card"
                }
                onClick={() => pick(open, d.file)}
              >
                <span className="template-card__name">{d.name}</span>
                <span className="template-card__kind">{d.file}</span>
              </button>
            ))}
          </div>
          <div className="design-strip__panel-actions">
            <button
              type="button"
              className="btn-like btn-like--ghost btn-sm"
              onClick={() => {
                setFinding(open);
                onOpen(null);
              }}
            >
              Find a design…
            </button>
            <label className="btn-like btn-like--ghost btn-sm">
              Upload a PNG…
              <input
                type="file"
                accept="image/png"
                hidden
                onChange={(e) => {
                  const file = e.currentTarget.files?.[0];
                  e.currentTarget.value = "";
                  if (file === undefined) return;
                  onOpen(null);
                  void upload(open, file);
                }}
              />
            </label>
          </div>
        </div>
      )}

      {finding !== null && (
        <ArtworkPicker
          title={`Design for ${targetLabel(finding)}`}
          hint={finderHint(finding, users)}
          cloth={finding.kind === "one" ? TILE.neutral : TILE[finding.tone]}
          current={slotFile(design, finding)}
          library={library}
          onPick={(ref) => pick(finding, ref)}
          onClose={() => setFinding(null)}
        />
      )}

      {choosing !== null && (
        <ChooseBaseDialog
          light={choosing.light}
          dark={choosing.dark}
          own={own}
          onKeep={(ref) => {
            setChoosing(null);
            onChange(keepOne(design, ref));
          }}
          onCancel={() => setChoosing(null)}
        />
      )}
    </div>
  );
}

function SlotName({
  uploading,
  file,
  emptyText,
}: {
  uploading: string | null;
  file: string | null;
  emptyText: string;
}) {
  if (uploading !== null) {
    return (
      <div className="design-row__name" role="status">
        Uploading {uploading}…
      </div>
    );
  }
  if (file !== null) return <div className="design-row__name">{refName(file)}</div>;
  return <div className="design-row__name design-row__name--empty">{emptyText}</div>;
}

function Slot({
  title,
  target,
  file,
  tones,
  usedBy,
  open,
  neededButEmpty,
  emptyText,
  holding,
  uploading,
  onChange,
  onFile,
}: {
  title: string;
  target: SlotTarget;
  file: string | null;
  tones: readonly Tone[];
  usedBy: string | null;
  open: boolean;
  neededButEmpty: boolean;
  emptyText: string;
  holding: boolean;
  uploading: string | null;
  onChange: () => void;
  onFile: (file: File) => void;
}) {
  const [over, setOver] = useState(false);
  const drag = useDragDepth(setOver);
  const label = targetLabel(target);
  const artwork = file === null ? null : listingDesignThumbnailUrl(refName(file));
  const cls = [
    "design-row",
    "design-row--slot",
    neededButEmpty ? "design-row--missing" : "",
    open ? "design-row--open" : "",
    holding ? "design-row--target" : "",
    over ? "design-row--over" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <section
      className={cls}
      aria-label={title}
      onDragEnter={(e) => drag.enter(e)}
      onDragLeave={() => drag.leave()}
      onDragOver={(e) => {
        if (hasFiles(e)) e.preventDefault();
      }}
      onDrop={(e) => {
        e.preventDefault();
        drag.reset();
        const dropped = e.dataTransfer.files[0];
        if (dropped !== undefined) onFile(dropped);
      }}
    >
      <div className="design-strip__shirts">
        {tones.map((tone) => (
          <ShirtThumb key={tone} cloth={TILE[tone]} artwork={uploading === null ? artwork : null} />
        ))}
        {uploading !== null && (
          <CircleNotchIcon className="design-strip__spin" weight="bold" aria-hidden="true" />
        )}
      </div>
      <div className="design-row__text">
        <div className="design-row__title">{title}</div>
        <SlotName uploading={uploading} file={file} emptyText={emptyText} />
        <div
          className={
            usedBy === null ? "design-row__users design-row__users--idle" : "design-row__users"
          }
        >
          {usedBy ?? "Not used — no colour you sell needs it"}
        </div>
        <button
          type="button"
          className="design-row__change"
          aria-label={`${file === null ? "Choose" : "Change"} design for ${label}`}
          aria-expanded={open}
          onClick={onChange}
        >
          {file === null ? "Choose" : "Change"} <CaretDownIcon weight="bold" aria-hidden="true" />
        </button>
      </div>
      {over && (
        <div className="design-strip__veil" aria-hidden="true">
          <UploadSimpleIcon weight="bold" />
          Drop to upload and use on {label}
        </div>
      )}
    </section>
  );
}
