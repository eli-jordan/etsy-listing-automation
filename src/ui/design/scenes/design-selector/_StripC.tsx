import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { useState } from "react";
import {
  current,
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
 * C · Compact form rows. The quietest option: a label column and a value,
 * like the rest of the editor's settings. A checkbox under the row adds a
 * second row for dark shirts. Dropping a file on a row turns that row into
 * a drop zone that names exactly what it will replace.
 */
export function StripC({ api, start = {} }: { api: StripApi; start?: StripStart }) {
  const split = api.base.mode === "light-dark";
  const keys: Key[] = split ? ["light", "dark"] : ["one"];
  const [open, setOpen] = useState<Key | null>(null);
  const { uploading, upload } = useUploads(api, start.uploading);

  return (
    <div className="design-select ds-c">
      <div className="ds-c__rows">
        {keys.map((k) => (
          <Row
            key={k}
            api={api}
            k={k}
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
      <label className="ds-c__check">
        <input
          type="checkbox"
          checked={split}
          onChange={() => {
            setOpen(null);
            if (split) api.onLink();
            else api.onUnlink();
          }}
        />
        Use a different design on dark shirts
      </label>
      {open !== null && (
        <RecentPanel api={api} k={open} onDone={() => setOpen(null)} onFile={(f) => void upload(open, f)} />
      )}
    </div>
  );
}

function Row({
  api,
  k,
  open,
  busy,
  dragging,
  onToggle,
  onFile,
}: {
  api: StripApi;
  k: Key;
  open: boolean;
  busy: string | undefined;
  dragging: boolean;
  onToggle: () => void;
  onFile: (f: File) => void;
}) {
  const drop = useDrop(onFile, dragging);
  const design = current(api.base, k);
  return (
    <div {...drop.props} className={drop.over ? "ds-c__row ds-c__row--over" : "ds-c__row"}>
      <span className="ds-c__key">{k === "one" ? "Design" : k === "light" ? "Light shirts" : "Dark shirts"}</span>
      {drop.over ? (
        <span className="ds-c__dropmsg">
          Drop to upload{design ? ` and replace ${design.name}` : ""} on {keyLabel(k)}
        </span>
      ) : (
        <>
          <Thumb design={design} tile={tileFor(k)} size={34} busy={busy !== undefined} />
          <span className={design === null && busy === undefined ? "ds-name ds-name--empty" : "ds-name"}>
            {busy !== undefined ? `Uploading ${busy}…` : (design?.name ?? "No design yet")}
          </span>
          <button type="button" className="design-row__change ds-change" aria-expanded={open} onClick={onToggle}>
            {design === null ? "Choose" : "Change"} <CaretDownIcon weight="bold" aria-hidden="true" />
          </button>
          <span className="ds-c__users">{printsOn(api, k)}</span>
          <span className="ds-c__hint">Drop a file to replace</span>
        </>
      )}
    </div>
  );
}
