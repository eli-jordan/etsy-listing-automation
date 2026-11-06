import { PlusIcon } from "@phosphor-icons/react/dist/csr/Plus";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useEffect, useRef, useState } from "react";
import { LABEL_CAP_MESSAGE, MAX_LABELS, labelRefusal, tidiedLabel } from "./labelRules";

const MAX_SUGGESTIONS = 6;

/** Labels on other templates as this one would save them. A hand-edited label
 * that breaks the rules stays on its own template but is not offered here,
 * since saving it on another would be refused. */
function suggestable(known: string[], held: string[]): string[] {
  const holds = new Set(held.map(tidiedLabel));
  const tidied = new Set(known.map(tidiedLabel));
  return [...tidied].filter((label) => !holds.has(label) && labelRefusal(label) === null).sort();
}

function Option({ onPick, children }: { onPick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={false}
      className="label-bar__option"
      onClick={onPick}
    >
      {children}
    </button>
  );
}

function AddLabel({
  suggestions,
  held,
  onAdd,
  onClose,
}: {
  suggestions: string[];
  held: string[];
  onAdd: (label: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const term = tidiedLabel(text);
  const shown = suggestions.filter((label) => label.includes(term)).slice(0, MAX_SUGGESTIONS);
  const isNew =
    term.length > 0 && !suggestions.includes(term) && !held.map(tidiedLabel).includes(term);
  const reason = isNew ? labelRefusal(term) : null;
  const creatable = isNew && reason === null;

  const onEnter = () => {
    const label = shown[0] ?? (creatable ? term : null);
    if (term && label) onAdd(label);
  };

  return (
    <div className="label-bar__combo">
      <input
        className="input label-bar__input"
        autoFocus
        aria-label="Add a label"
        placeholder="Add a label…"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          // Both presses are ours: the mask editor also leaves on Escape, and
          // an Enter left to run on would click the Add label button that focus
          // returns to, opening the field again.
          if (event.key !== "Enter" && event.key !== "Escape") return;
          event.preventDefault();
          if (event.key === "Enter") onEnter();
          else onClose();
        }}
      />
      {(shown.length > 0 || isNew) && (
        <div className="label-bar__menu">
          <div role="listbox" aria-label="Label suggestions">
            {shown.map((label) => (
              <Option key={label} onPick={() => onAdd(label)}>
                {label}
              </Option>
            ))}
            {creatable && (
              <Option onPick={() => onAdd(term)}>
                <PlusIcon className="label-bar__icon" /> Create “{term}”
              </Option>
            )}
          </div>
          {reason && <p className="label-bar__reason">{reason}</p>}
        </div>
      )}
    </div>
  );
}

/**
 * The open template's labels, above its photo.
 *
 * Chips show `saved`, so one appears or goes only when the save lands (spec
 * *Saving*); until then the app's save status reports progress. Every edit
 * builds on `draft`, so quick edits land together and a failed one rides the
 * next save.
 */
export function LabelsBar({
  saved,
  draft,
  known,
  failure,
  onChange,
}: {
  saved: string[];
  draft: string[];
  /** Every label in the catalog, this template's included. */
  known: string[];
  failure: string | null;
  onChange: (labels: string[]) => void;
}) {
  const [adding, setAdding] = useState(false);
  const addButton = useRef<HTMLButtonElement>(null);
  const closing = useRef(false);
  const full = draft.length >= MAX_LABELS;

  // The field held focus, and leaving with it would drop the seller at the top
  // of the page. The button only exists once the field has gone.
  useEffect(() => {
    if (adding || !closing.current) return;
    closing.current = false;
    addButton.current?.focus();
  }, [adding]);

  const close = () => {
    closing.current = true;
    setAdding(false);
  };

  return (
    <div className="label-bar" role="group" aria-label="Labels">
      <span className="label-bar__title">Labels</span>
      {saved.map((label) => (
        <span key={label} className="tag tag-neutral label-bar__chip">
          {label}
          <button
            type="button"
            className="label-bar__remove"
            aria-label={`Remove ${label}`}
            onClick={() => onChange(draft.filter((held) => held !== label))}
          >
            <XIcon weight="bold" />
          </button>
        </span>
      ))}
      {adding ? (
        <AddLabel
          suggestions={suggestable(known, draft)}
          held={draft}
          onAdd={(label) => {
            onChange([...draft, label]);
            close();
          }}
          onClose={close}
        />
      ) : (
        <button
          ref={addButton}
          type="button"
          className="label-bar__add"
          disabled={full}
          title={full ? LABEL_CAP_MESSAGE : undefined}
          onClick={() => setAdding(true)}
        >
          <PlusIcon className="label-bar__icon" /> Add label
        </button>
      )}
      {full && <span className="app__meta">{LABEL_CAP_MESSAGE}</span>}
      {failure && (
        <p className="label-bar__failure" role="alert">
          {failure}
        </p>
      )}
    </div>
  );
}
