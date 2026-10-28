import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { UploadSimpleIcon } from "@phosphor-icons/react/dist/csr/UploadSimple";
import { useRef, useState, type DragEvent } from "react";
import { ShirtPreview } from "../../screens/multiArtwork/ShirtPreview";
import { TILE } from "../../screens/multiArtwork/artwork";
import {
  current,
  printsOn,
  RecentPanel,
  useDrop,
  useUploads,
  type Key,
  type StripApi,
  type StripStart,
} from "./_shared";

/**
 * D · The drop picks the scope. At rest: a light and a dark shirt wearing
 * what they print, so the split is visible before anyone asks for it. Hold a
 * file over the selector and it opens into labelled targets - all shirts,
 * light only, dark only - so dropping is also how you split (or rejoin).
 */
export function StripD({ api, start = {} }: { api: StripApi; start?: StripStart }) {
  const split = api.base.mode === "light-dark";
  const [open, setOpen] = useState<Key | null>(null);
  const { uploading, upload } = useUploads(api, start.uploading);
  const [holding, setHolding] = useState(start.dragging !== undefined);
  const depth = useRef(0);
  const busyKey = (Object.keys(uploading) as Key[]).find((k) => uploading[k] !== undefined);

  const files = (e: DragEvent) => Array.from(e.dataTransfer.types).includes("Files");
  const hold = {
    onDragEnter: (e: DragEvent) => {
      if (!files(e)) return;
      depth.current += 1;
      setHolding(true);
    },
    onDragLeave: () => {
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setHolding(false);
    },
    onDrop: () => {
      depth.current = 0;
      setHolding(false);
    },
  };
  const drop = (k: Key) => (f: File) => {
    setHolding(false);
    void upload(k, f);
  };
  const zones: { k: Key; title: string; sub: string }[] = split
    ? [
        { k: "light", title: "Light shirts", sub: "replace the light design" },
        { k: "dark", title: "Dark shirts", sub: "replace the dark design" },
        { k: "one", title: "All shirts", sub: "back to one design" },
      ]
    : [
        { k: "one", title: "All shirts", sub: "replace the design everywhere" },
        { k: "light", title: "Light shirts only", sub: "splits into light & dark" },
        { k: "dark", title: "Dark shirts only", sub: "splits into light & dark" },
      ];

  return (
    <div className="design-select ds-d">
      <div className={holding ? "ds-d__card ds-d__card--holding" : "ds-d__card"} {...hold}>
        <div className="ds-d__shirts">
          {(["light", "dark"] as const).map((tone) => {
            const design = current(api.base, tone);
            const busy = busyKey === tone || busyKey === "one";
            return (
              <div key={tone} className="ds-d__shirt">
                <ShirtPreview colour={TILE[tone]} artwork={busy ? null : (design?.url ?? null)} label={`${tone} shirt`} />
                {busy && <span className="ds-d__busy">Uploading…</span>}
              </div>
            );
          })}
        </div>
        <div className="ds-d__text">
          {split ? (
            <div className="ds-d__pair">
              {(["light", "dark"] as const).map((tone) => (
                <div key={tone}>
                  <div className="ds-label">{tone === "light" ? "Light shirts" : "Dark shirts"}</div>
                  <div className="ds-name">{current(api.base, tone)?.name ?? "No design yet"}</div>
                  <div className="ds-sub">{printsOn(api, tone)}</div>
                  <button type="button" className="design-row__change ds-change" onClick={() => setOpen(open === tone ? null : tone)}>
                    Change <CaretDownIcon weight="bold" aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div>
              <div className="ds-label">One design on every shirt</div>
              <div className="ds-name ds-name--lg">{current(api.base, "one")?.name ?? "No design yet"}</div>
              <button type="button" className="design-row__change ds-change" onClick={() => setOpen(open === "one" ? null : "one")}>
                Change <CaretDownIcon weight="bold" aria-hidden="true" />
              </button>
            </div>
          )}
          <div className="ds-d__foot">
            <button
              type="button"
              className="ds-textbtn"
              onClick={() => {
                setOpen(null);
                if (split) api.onLink();
                else api.onUnlink();
              }}
            >
              {split ? "Use one design for all shirts" : "Use different designs on light & dark shirts"}
            </button>
            <span className="ds-d__drophint">
              <UploadSimpleIcon weight="bold" aria-hidden="true" /> Drop a file here to upload
            </span>
          </div>
        </div>

        {holding && (
          <div className="ds-d__zones">
            {zones.map((z, i) => (
              <Zone key={z.k} {...z} wide={i === 0} start={start.dragging === z.k} onFile={drop(z.k)} />
            ))}
          </div>
        )}
      </div>
      {open !== null && (
        <RecentPanel api={api} k={open} onDone={() => setOpen(null)} onFile={(f) => void upload(open, f)} />
      )}
    </div>
  );
}

function Zone({
  title,
  sub,
  k,
  wide,
  start,
  onFile,
}: {
  title: string;
  sub: string;
  k: Key;
  wide: boolean;
  start: boolean;
  onFile: (f: File) => void;
}) {
  const drop = useDrop(onFile, start);
  return (
    <div
      {...drop.props}
      className={["ds-d__zone", `ds-d__zone--${k}`, wide && "ds-d__zone--wide", drop.over && "ds-d__zone--over"]
        .filter(Boolean)
        .join(" ")}
    >
      <UploadSimpleIcon weight="bold" aria-hidden="true" />
      <strong>{title}</strong>
      <span>{sub}</span>
    </div>
  );
}
