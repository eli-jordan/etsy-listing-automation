import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { useState } from "react";
import {
  Browse,
  current,
  DropVeil,
  keyLabel,
  printsOn,
  RecentPanel,
  Thumb,
  tileFor,
  useDrop,
  useUploads,
  type Key,
  type StripApi,
  type StripStart,
} from "./_shared";

/**
 * A · Switch card. One card holds the selector. A switch on its right edge,
 * "Different designs for light & dark shirts", splits the card's body into two
 * halves in place - the card never moves or grows taller. Each half (or the
 * whole card, before the split) is its own drop target.
 */
export function StripA({ api, start = {} }: { api: StripApi; start?: StripStart }) {
  const split = api.base.mode === "light-dark";
  const [open, setOpen] = useState<Key | null>(null);
  const { uploading, upload } = useUploads(api, start.uploading);
  const keys: Key[] = split ? ["light", "dark"] : ["one"];

  return (
    <div className="design-select ds-a">
      <div className="ds-a__card">
        <div className="ds-a__body">
          {keys.map((k) => (
            <Half
              key={k}
              api={api}
              k={k}
              split={split}
              open={open === k}
              busy={uploading[k]}
              dragging={start.dragging === k}
              onToggle={() => setOpen(open === k ? null : k)}
              onFile={(f) => {
                setOpen(null);
                void upload(k, f);
              }}
            />
          ))}
        </div>
        <label className="ds-a__mode">
          <button
            type="button"
            role="switch"
            aria-checked={split}
            className={split ? "switch switch--on" : "switch"}
            onClick={() => {
              setOpen(null);
              if (split) api.onLink();
              else api.onUnlink();
            }}
          >
            <span className="switch__knob" />
          </button>
          <span>
            Different designs for
            <br />
            light &amp; dark shirts
          </span>
        </label>
      </div>
      {open !== null && (
        <RecentPanel api={api} k={open} onDone={() => setOpen(null)} onFile={(f) => void upload(open, f)} />
      )}
    </div>
  );
}

function Half({
  api,
  k,
  split,
  open,
  busy,
  dragging,
  onToggle,
  onFile,
}: {
  api: StripApi;
  k: Key;
  split: boolean;
  open: boolean;
  busy: string | undefined;
  dragging: boolean;
  onToggle: () => void;
  onFile: (f: File) => void;
}) {
  const drop = useDrop(onFile, dragging);
  const design = current(api.base, k);
  const missing = split && design === null;
  return (
    <div
      {...drop.props}
      className={["ds-a__half", drop.over && "ds-over", missing && "ds-a__half--missing"].filter(Boolean).join(" ")}
    >
      <Thumb design={design} tile={tileFor(k)} size={56} busy={busy !== undefined} />
      <div className="ds-a__text">
        <div className="ds-label">{k === "one" ? "Design" : k === "light" ? "Light shirts" : "Dark shirts"}</div>
        {busy !== undefined ? (
          <div className="ds-name">Uploading {busy}…</div>
        ) : design !== null ? (
          <div className="ds-name">{design.name}</div>
        ) : (
          <div className="ds-name ds-name--empty">
            Drop a file or <Browse onFile={onFile}>browse</Browse>
          </div>
        )}
        <div className="ds-sub">{printsOn(api, k)}</div>
      </div>
      <button type="button" className="design-row__change ds-change" aria-expanded={open} onClick={onToggle}>
        {design === null ? "Choose" : "Change"} <CaretDownIcon weight="bold" aria-hidden="true" />
      </button>
      {drop.over && <DropVeil>Drop to upload and use on {keyLabel(k)}</DropVeil>}
    </div>
  );
}
