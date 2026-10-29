import { MagnifyingGlassIcon } from "@phosphor-icons/react/dist/csr/MagnifyingGlass";
import { PlusIcon } from "@phosphor-icons/react/dist/csr/Plus";
import { useState } from "react";
import {
  Browse,
  current,
  DropVeil,
  keyLabel,
  targetOf,
  Thumb,
  tileFor,
  useDrop,
  useUploads,
  type Key,
  type StripApi,
  type StripStart,
} from "./_shared";

/**
 * B · Mode tabs + design rail. No dropdowns: a segmented control picks the
 * mode, the chosen design(s) sit as big tiles, and recent designs are always
 * on show in a rail beside them - one click applies one to the selected tile.
 * Split, the two tiles take turns being the one the rail fills.
 */
export function StripB({ api, start = {} }: { api: StripApi; start?: StripStart }) {
  const split = api.base.mode === "light-dark";
  const keys: Key[] = split ? ["light", "dark"] : ["one"];
  const [chosen, setChosen] = useState<Key>("light");
  const active: Key = split ? chosen : "one";
  const { uploading, upload } = useUploads(api, start.uploading);
  const railDrop = useDrop((f) => void upload(active, f), start.dragging === "card");

  return (
    <div className="design-select ds-b">
      <div className="ds-b__mode">
        <span className="ds-label">Artwork</span>
        <div className="tabs seg" role="radiogroup" aria-label="Artwork">
          <button
            type="button"
            role="radio"
            aria-checked={!split}
            className={split ? "seg-opt" : "seg-opt seg-opt--on"}
            onClick={() => split && api.onLink()}
          >
            One design
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={split}
            className={split ? "seg-opt seg-opt--on" : "seg-opt"}
            onClick={() => !split && api.onUnlink()}
          >
            Light &amp; dark
          </button>
        </div>
      </div>

      <div className="ds-b__tiles">
        {keys.map((k) => (
          <BigTile
            key={k}
            api={api}
            k={k}
            active={split && active === k}
            busy={uploading[k]}
            dragging={start.dragging === k}
            onSelect={() => setChosen(k as "light" | "dark")}
            onFile={(f) => {
              if (k !== "one") setChosen(k);
              void upload(k, f);
            }}
          />
        ))}
      </div>

      <div className={railDrop.over ? "ds-b__rail ds-over" : "ds-b__rail"} {...railDrop.props}>
        <div className="ds-b__railhead">
          <span className="ds-sub">
            Recent - click to use on <strong>{keyLabel(active)}</strong>
          </span>
          <button type="button" className="ds-textbtn" onClick={() => api.onFind(targetOf(active))}>
            <MagnifyingGlassIcon weight="bold" aria-hidden="true" /> All designs
          </button>
        </div>
        <div className="ds-b__railrow">
          {api.library.slice(0, split ? 2 : 5).map((d) => (
            <button
              key={d.file}
              type="button"
              title={d.name}
              className={current(api.base, active)?.file === d.file ? "ds-b__mini ds-b__mini--on" : "ds-b__mini"}
              onClick={() => api.onPick(targetOf(active), d)}
            >
              <Thumb design={d} tile={tileFor(active)} size={44} />
            </button>
          ))}
          <Browse className="ds-b__add" onFile={(f) => void upload(active, f)}>
            <PlusIcon weight="bold" aria-hidden="true" />
            <span>Upload or drop</span>
          </Browse>
        </div>
        {railDrop.over && <DropVeil>Drop to upload and use on {keyLabel(active)}</DropVeil>}
      </div>
    </div>
  );
}

function BigTile({
  api,
  k,
  active,
  busy,
  dragging,
  onSelect,
  onFile,
}: {
  api: StripApi;
  k: Key;
  active: boolean;
  busy: string | undefined;
  dragging: boolean;
  onSelect: () => void;
  onFile: (f: File) => void;
}) {
  const drop = useDrop(onFile, dragging);
  const design = current(api.base, k);
  return (
    <button
      type="button"
      {...drop.props}
      onClick={onSelect}
      aria-pressed={k === "one" ? undefined : active}
      className={["ds-b__tile", active && "ds-b__tile--active", drop.over && "ds-over"].filter(Boolean).join(" ")}
    >
      <Thumb design={design} tile={tileFor(k)} size={k === "one" ? 84 : 64} busy={busy !== undefined} />
      <span className="ds-b__cap">
        <span className="ds-label">{k === "one" ? "All shirts" : k === "light" ? "Light shirts" : "Dark shirts"}</span>
        <span className={design === null && busy === undefined ? "ds-name ds-name--empty" : "ds-name"}>
          {busy !== undefined ? `Uploading ${busy}…` : (design?.name ?? "Pick or drop one")}
        </span>
      </span>
      {drop.over && <DropVeil>Drop here</DropVeil>}
    </button>
  );
}
