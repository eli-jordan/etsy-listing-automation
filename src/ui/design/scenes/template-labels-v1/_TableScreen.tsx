// Direction C: every template is a row and every label group a column. Gaps
// show as empty cells, and a saved view is a named set of column filters.
import { BookmarkSimpleIcon } from "@phosphor-icons/react/dist/csr/BookmarkSimple";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { FunnelIcon } from "@phosphor-icons/react/dist/csr/Funnel";
import { PlusIcon } from "@phosphor-icons/react/dist/csr/Plus";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useMemo, useState } from "react";
import {
  type GroupId,
  groups,
  hasNoModel,
  type LabelGroup,
  type LabelTemplate,
  labelsIn,
  matches,
  withImpliedShot,
  type Selection,
  templates as fixtures,
} from "./_fixtures";

type ViewId = "all" | "christmas" | "flat-lays" | "gaps";

interface SavedView {
  id: ViewId;
  title: string;
  selection: Selection;
  gapsOnly?: boolean;
}

const views: SavedView[] = [
  { id: "all", title: "All", selection: {} },
  { id: "christmas", title: "Christmas", selection: { theme: ["Christmas"] } },
  { id: "flat-lays", title: "Flat lays", selection: { shot: ["Flat lay"] } },
  { id: "gaps", title: "Needs labels", selection: {}, gapsOnly: true },
];

const isGap = (t: LabelTemplate) => t.labels.length === 0;

/** Which popover is open: a column's filter, or one cell's editor. */
type Open = { kind: "filter"; group: GroupId } | { kind: "cell"; group: GroupId; name: string } | null;

function CellMenu({
  group,
  held,
  onPick,
}: {
  group: LabelGroup;
  held: string[];
  onPick: (label: string) => void;
}) {
  return (
    <div className="tl-pop tl-cellmenu" role="listbox" aria-label={group.title}>
      {group.options.map((label) => (
        <button
          key={label}
          type="button"
          role="option"
          aria-selected={held.includes(label)}
          className="tl-option"
          onClick={() => onPick(label)}
        >
          <span className="tl-option__check">{held.includes(label) && <CheckIcon weight="bold" />}</span>
          {label}
        </button>
      ))}
      {group.multiple && (
        <button type="button" className="tl-option tl-option--new">
          <PlusIcon className="tl-icon" /> New theme
        </button>
      )}
    </div>
  );
}

function FilterMenu({
  group,
  selection,
  rows,
  onToggle,
}: {
  group: LabelGroup;
  selection: Selection;
  rows: LabelTemplate[];
  onToggle: (label: string) => void;
}) {
  const chosen = selection[group.id] ?? [];
  return (
    <div className="tl-pop tl-cellmenu" role="group" aria-label={`Filter ${group.title}`}>
      {group.options.map((label) => {
        const count = rows.filter(
          (t) => matches(t, selection, group.id) && t.labels.includes(label),
        ).length;
        return (
          <button
            key={label}
            type="button"
            className="tl-option"
            aria-pressed={chosen.includes(label)}
            disabled={count === 0 && !chosen.includes(label)}
            onClick={() => onToggle(label)}
          >
            <span className="tl-option__check">{chosen.includes(label) && <CheckIcon weight="bold" />}</span>
            {label}
            <span className="tl-count">{count}</span>
          </button>
        );
      })}
    </div>
  );
}

export function TableScreen({
  initialView = "all",
  initialOpen = null,
}: {
  initialView?: ViewId;
  initialOpen?: Open;
}) {
  const start = views.find((v) => v.id === initialView)!;
  const [view, setView] = useState<ViewId | null>(initialView);
  const [selection, setSelection] = useState<Selection>(start.selection);
  const [gapsOnly, setGapsOnly] = useState(Boolean(start.gapsOnly));
  const [open, setOpen] = useState<Open>(initialOpen);
  const [labelsOf, setLabelsOf] = useState<Record<string, string[]>>(() =>
    Object.fromEntries(fixtures.map((t) => [t.name, t.labels])),
  );

  const rows = useMemo(
    () => fixtures.map((t) => ({ ...t, labels: labelsOf[t.name] ?? [] })),
    [labelsOf],
  );
  const pool = gapsOnly ? rows.filter(isGap) : rows;
  const shown = pool.filter((t) => matches(t, selection));
  const active = groups.flatMap((g) =>
    (selection[g.id] ?? []).length ? [{ group: g, values: selection[g.id] ?? [] }] : [],
  );

  const chooseView = (next: SavedView) => {
    setView(next.id);
    setSelection(next.selection);
    setGapsOnly(Boolean(next.gapsOnly));
    setOpen(null);
  };
  const toggleFilter = (id: GroupId, label: string) => {
    setView(null);
    setSelection((current) => {
      const chosen = current[id] ?? [];
      return {
        ...current,
        [id]: chosen.includes(label) ? chosen.filter((l) => l !== label) : [...chosen, label],
      };
    });
  };
  const setCell = (template: LabelTemplate, group: LabelGroup, label: string) => {
    setLabelsOf((current) => {
      const held = current[template.name] ?? [];
      const has = held.includes(label);
      const next = group.multiple
        ? has
          ? held.filter((l) => l !== label)
          : [...held, label]
        : [...held.filter((l) => !group.options.includes(l)), ...(has ? [] : [label])];
      return { ...current, [template.name]: withImpliedShot(next) };
    });
    if (!group.multiple) setOpen(null);
  };
  const toggleOpen = (next: NonNullable<Open>) =>
    setOpen((current) => (JSON.stringify(current) === JSON.stringify(next) ? null : next));

  return (
    <div className="tl-page">
      <div className="page-head">
        <h1 className="page-head__title">Mockup Templates</h1>
        <span className="page-head__meta">
          {shown.length === rows.length
            ? `${rows.length} templates`
            : `${shown.length} of ${rows.length} templates`}
        </span>
      </div>

      <div className="tl-views" role="tablist" aria-label="Saved views">
        {views.map((v) => {
          const count = (v.gapsOnly ? rows.filter(isGap) : rows).filter((t) =>
            matches(t, v.selection),
          ).length;
          return (
            <button
              key={v.id}
              type="button"
              role="tab"
              aria-selected={view === v.id}
              className={`tl-view${view === v.id ? " tl-view--on" : ""}`}
              onClick={() => chooseView(v)}
            >
              {v.title} <span className="tl-count">{count}</span>
            </button>
          );
        })}
        {view === null && (
          <button type="button" className="tl-add">
            <BookmarkSimpleIcon className="tl-icon" /> Save view
          </button>
        )}
      </div>

      {active.length > 0 && (
        <div className="tl-active">
          {active.map(({ group, values }) => (
            <span key={group.id} className="tag tag-neutral tl-chip">
              {group.title} is {values.join(" or ")}
              <button
                type="button"
                className="tl-chip__x"
                aria-label={`Clear ${group.title} filter`}
                onClick={() => {
                  setView(null);
                  setSelection((current) => ({ ...current, [group.id]: [] }));
                }}
              >
                <XIcon weight="bold" />
              </button>
            </span>
          ))}
        </div>
      )}

      <table className="tl-table">
        <thead>
          <tr>
            <th scope="col" className="tl-table__name">
              Template
            </th>
            {groups.map((group) => {
              const filtered = (selection[group.id] ?? []).length > 0;
              const isOpen = open?.kind === "filter" && open.group === group.id;
              return (
                <th key={group.id} scope="col" className="tl-table__anchor">
                  <button
                    type="button"
                    className={`tl-colhead${filtered ? " tl-colhead--on" : ""}`}
                    aria-expanded={isOpen}
                    onClick={() => toggleOpen({ kind: "filter", group: group.id })}
                  >
                    {group.title} <FunnelIcon weight={filtered ? "fill" : "regular"} className="tl-icon" />
                  </button>
                  {isOpen && (
                    <FilterMenu
                      group={group}
                      selection={selection}
                      rows={pool}
                      onToggle={(label) => toggleFilter(group.id, label)}
                    />
                  )}
                </th>
              );
            })}
            <th scope="col" className="tl-table__status">
              Status
            </th>
          </tr>
        </thead>
        <tbody>
          {shown.map((t) => (
            <tr key={t.name}>
              <th scope="row" className="tl-table__name">
                <span className="tl-rowname">
                  <img src={t.src} alt="" />
                  <span>{t.name.replace("cc1717-", "")}</span>
                </span>
              </th>
              {groups.map((group) => {
                const held = labelsIn(t, group);
                const isOpen =
                  open?.kind === "cell" && open.group === group.id && open.name === t.name;
                const noModel = group.id === "model" && held.length === 0 && hasNoModel(t);
                return (
                  <td key={group.id} className="tl-table__anchor">
                    <button
                      type="button"
                      className={`tl-cell${isOpen ? " tl-cell--open" : ""}`}
                      aria-expanded={isOpen}
                      aria-label={`${group.title} for ${t.name}`}
                      onClick={() => toggleOpen({ kind: "cell", group: group.id, name: t.name })}
                    >
                      {held.map((label) => (
                        <span key={label} className="tag tag-neutral">
                          {label}
                        </span>
                      ))}
                      {held.length === 0 &&
                        (noModel ? (
                          <span className="tl-cell__none">No model</span>
                        ) : group.id === "theme" ? (
                          <span className="tl-cell__none">None</span>
                        ) : (
                          <span className="tl-cell__gap">
                            <PlusIcon className="tl-icon" /> Add
                          </span>
                        ))}
                    </button>
                    {isOpen && (
                      <CellMenu group={group} held={held} onPick={(label) => setCell(t, group, label)} />
                    )}
                  </td>
                );
              })}
              <td className="tl-table__status">
                <span
                  className={`tag mg-status${t.status === "Ready" ? " mg-status--ready" : ""}`}
                >
                  {t.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {shown.length === 0 && (
        <div className="tl-empty">
          <p>No templates match these filters.</p>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => chooseView(views[0]!)}
          >
            Show all templates
          </button>
        </div>
      )}
    </div>
  );
}
