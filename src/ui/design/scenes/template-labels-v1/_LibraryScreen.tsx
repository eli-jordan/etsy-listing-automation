// Direction B: the page opens on the photos. Labels sit in managed groups down
// the side, and many templates can be labelled at once.
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { MinusIcon } from "@phosphor-icons/react/dist/csr/Minus";
import { TagIcon } from "@phosphor-icons/react/dist/csr/Tag";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useMemo, useState } from "react";
import {
  type GroupId,
  groups,
  type LabelTemplate,
  matches,
  withImpliedShot,
  type Selection,
  templates as fixtures,
} from "./_fixtures";

function Tick({ state }: { state: "on" | "some" | "off" }) {
  return (
    <span className={`tl-tick tl-tick--${state}`} aria-hidden="true">
      {state === "on" && <CheckIcon weight="bold" />}
      {state === "some" && <MinusIcon weight="bold" />}
    </span>
  );
}

function Tile({
  template,
  picked,
  onPick,
}: {
  template: LabelTemplate;
  picked: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      className={`tl-tile${picked ? " tl-tile--picked" : ""}`}
      aria-pressed={picked}
      onClick={onPick}
    >
      <span className="tl-tile__photo">
        <img src={template.src} alt="" />
        <span className="tl-tile__check">
          <Tick state={picked ? "on" : "off"} />
        </span>
      </span>
      <span className="tl-tile__name">{template.name.replace("cc1717-", "")}</span>
      <span className={`tl-tile__labels${template.labels.length ? "" : " tl-tile__labels--none"}`}>
        {template.labels.length ? template.labels.join(" · ") : "No labels"}
      </span>
    </button>
  );
}

function BulkMenu({
  picked,
  labelsOf,
  onToggle,
}: {
  picked: string[];
  labelsOf: Record<string, string[]>;
  onToggle: (label: string, on: boolean) => void;
}) {
  return (
    <div className="tl-pop tl-bulk__menu" role="group" aria-label="Labels for the selected templates">
      {groups.map((group) => (
        <div key={group.id} className="tl-bulk__group">
          <span className="tl-facet__title">{group.title}</span>
          {group.options.map((label) => {
            const holding = picked.filter((name) => labelsOf[name]?.includes(label)).length;
            const state = holding === 0 ? "off" : holding === picked.length ? "on" : "some";
            return (
              <button
                key={label}
                type="button"
                className="tl-option"
                aria-pressed={state === "on"}
                onClick={() => onToggle(label, state !== "on")}
              >
                <Tick state={state} /> {label}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}

export function LibraryScreen({
  initialSelection = {},
  initialUnlabelled = false,
  initialPicked = [],
  initialMenu = false,
}: {
  initialSelection?: Selection;
  initialUnlabelled?: boolean;
  initialPicked?: string[];
  initialMenu?: boolean;
}) {
  const [selection, setSelection] = useState<Selection>(initialSelection);
  const [unlabelled, setUnlabelled] = useState(initialUnlabelled);
  const [picked, setPicked] = useState(initialPicked);
  const [menu, setMenu] = useState(initialMenu);
  const [labelsOf, setLabelsOf] = useState<Record<string, string[]>>(() =>
    Object.fromEntries(fixtures.map((t) => [t.name, t.labels])),
  );

  const library = useMemo(
    () => fixtures.map((t) => ({ ...t, labels: labelsOf[t.name] ?? [] })),
    [labelsOf],
  );
  // Labelling a selected tile must not whisk it out of the "No labels yet" view.
  const pool = unlabelled
    ? library.filter((t) => t.labels.length === 0 || picked.includes(t.name))
    : library;
  const shown = pool.filter((t) => matches(t, selection));
  const bare = library.filter((t) => t.labels.length === 0).length;
  const active = groups.flatMap((g) => (selection[g.id] ?? []).map((label) => ({ id: g.id, label })));

  const toggleFacet = (id: GroupId, label: string) =>
    setSelection((current) => {
      const chosen = current[id] ?? [];
      return {
        ...current,
        [id]: chosen.includes(label) ? chosen.filter((l) => l !== label) : [...chosen, label],
      };
    });
  const togglePick = (name: string) =>
    setPicked((current) =>
      current.includes(name) ? current.filter((n) => n !== name) : [...current, name],
    );
  const clearAll = () => {
    setSelection({});
    setUnlabelled(false);
  };
  const applyLabel = (label: string, on: boolean) => {
    // A shot or model replaces its group's value; themes stack.
    const group = groups.find((g) => g.options.includes(label));
    setLabelsOf((current) => {
      const next = { ...current };
      for (const name of picked) {
        const held = (next[name] ?? []).filter(
          (l) => l !== label && (group?.multiple || !group?.options.includes(l)),
        );
        next[name] = withImpliedShot(on ? [...held, label] : held);
      }
      return next;
    });
  };

  return (
    <div className="tl-page">
      <div className="page-head">
        <h1 className="page-head__title">Mockup Templates</h1>
        <span className="page-head__meta">
          {shown.length === library.length
            ? `${library.length} templates`
            : `${shown.length} of ${library.length} templates`}
        </span>
      </div>

      <div className="tl-library">
        <aside className="tl-facets" aria-label="Filter by label">
          <button
            type="button"
            className={`tl-facet tl-facet--bare${unlabelled ? " tl-facet--on" : ""}`}
            aria-pressed={unlabelled}
            onClick={() => setUnlabelled((value) => !value)}
          >
            <Tick state={unlabelled ? "on" : "off"} />
            <span>No labels yet</span>
            <span className="tl-count">{bare}</span>
          </button>
          {groups.map((group) => (
            <section key={group.id} className="tl-facet-group">
              <h2 className="tl-facet__title">{group.title}</h2>
              {group.options.map((label) => {
                const on = (selection[group.id] ?? []).includes(label);
                const count = pool.filter(
                  (t) => matches(t, selection, group.id) && t.labels.includes(label),
                ).length;
                return (
                  <button
                    key={label}
                    type="button"
                    className={`tl-facet${on ? " tl-facet--on" : ""}`}
                    aria-pressed={on}
                    disabled={count === 0 && !on}
                    onClick={() => toggleFacet(group.id, label)}
                  >
                    <Tick state={on ? "on" : "off"} />
                    <span>{label}</span>
                    <span className="tl-count">{count}</span>
                  </button>
                );
              })}
            </section>
          ))}
          <button type="button" className="tl-link">
            Manage labels
          </button>
        </aside>

        <section className="tl-results" aria-label="Templates">
          {(active.length > 0 || unlabelled) && (
            <div className="tl-active">
              {unlabelled && (
                <span className="tag tag-neutral tl-chip">
                  No labels yet
                  <button
                    type="button"
                    className="tl-chip__x"
                    aria-label="Remove No labels yet"
                    onClick={() => setUnlabelled(false)}
                  >
                    <XIcon weight="bold" />
                  </button>
                </span>
              )}
              {active.map(({ id, label }) => (
                <span key={label} className="tag tag-neutral tl-chip">
                  {label}
                  <button
                    type="button"
                    className="tl-chip__x"
                    aria-label={`Remove ${label}`}
                    onClick={() => toggleFacet(id, label)}
                  >
                    <XIcon weight="bold" />
                  </button>
                </span>
              ))}
              <button type="button" className="tl-link" onClick={clearAll}>
                Clear all
              </button>
            </div>
          )}

          {shown.length === 0 ? (
            <div className="tl-empty">
              <p>No templates have all of these labels.</p>
              <button type="button" className="btn btn-secondary" onClick={clearAll}>
                Clear filters
              </button>
            </div>
          ) : (
            <div className="tl-grid">
              {shown.map((t) => (
                <Tile
                  key={t.name}
                  template={t}
                  picked={picked.includes(t.name)}
                  onPick={() => togglePick(t.name)}
                />
              ))}
            </div>
          )}
        </section>
      </div>

      {picked.length > 0 && (
        <div className="tl-bulk" role="toolbar" aria-label="Selected templates">
          <span className="tl-bulk__count">
            {picked.length} selected
          </span>
          <div className="tl-bulk__anchor">
            {menu && <BulkMenu picked={picked} labelsOf={labelsOf} onToggle={applyLabel} />}
            <button
              type="button"
              className="btn btn-primary"
              aria-expanded={menu}
              onClick={() => setMenu((value) => !value)}
            >
              <TagIcon className="tl-icon" /> Label
            </button>
          </div>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              setPicked([]);
              setMenu(false);
            }}
          >
            Deselect
          </button>
        </div>
      )}
    </div>
  );
}
