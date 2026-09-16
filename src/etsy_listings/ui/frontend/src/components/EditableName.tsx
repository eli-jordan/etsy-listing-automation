import { useRef, useState } from "react";

/**
 * The listing editor's page-head title, in both states a listing can have a
 * name in: one it already has (double-click to rename) and one it has not been
 * given yet (opens waiting, because there is nothing to double-click).
 *
 * It lives in `components/` rather than under `pages/editor/` for the reason
 * `StatusTag` and `OpenOnMenu` do -- head chrome that no single page owns.
 *
 * Nothing here validates. What makes a legal listing name is what makes a legal
 * *directory* name, and only `workspace` knows that (A8), so a refusal arrives
 * from the server as `error` and is shown beside the field.
 */

export interface NameRefusal {
  /** The name that was refused. Carried so the message can disappear on its
   * own once the text has moved on -- a refusal is about a particular name, and
   * one left standing over different text is claiming something untrue. */
  name: string;
  message: string;
}

export interface EditableNameProps {
  /** The committed name. `""` for a listing that has never been named. */
  value: string;
  /** Enter or blur, with the trimmed text -- and only when it is non-empty and
   * actually differs from `value`. Escape reverts and never commits, so a
   * double-click you did not mean costs nothing. */
  onCommit: (next: string) => void;
  error?: NameRefusal | null;
  /** A commit is in flight; the field stays open and read-only rather than
   * closing over a name that may yet be refused. */
  busy?: boolean;
  placeholder?: string;
  label?: string;
}

export function EditableName({
  value,
  onCommit,
  error = null,
  busy = false,
  placeholder = "Name this listing…",
  label = "Listing name",
}: EditableNameProps) {
  const [opened, setOpened] = useState(false);
  const [text, setText] = useState(value);
  const [committed, setCommitted] = useState(value);
  // A blur *caused by* Escape must not commit, and the browser fires blur after
  // the keydown either way -- so the key handler records what it decided and
  // the blur handler obeys it.
  const reverting = useRef(false);

  // Adjusting state while rendering, rather than in an effect: the name landed
  // (a rename went through, or this page moved to another listing) and the edit
  // buffer is about the old one.
  if (committed !== value) {
    setCommitted(value);
    setText(value);
    setOpened(false);
  }

  // Derived, not stored. A listing with no name has nothing to double-click, and
  // a refused name has to stay reachable for correcting.
  const refused = error !== null && text.trim() === error.name;
  const editing = opened || value === "" || refused;

  function commit() {
    const trimmed = text.trim();
    if (trimmed === "" || trimmed === value) {
      setText(value);
      setOpened(false);
      return;
    }
    // The field stays open until `value` catches up: a create can still be
    // refused, and closing over a name that was never written would show a
    // heading for a listing that does not exist.
    onCommit(trimmed);
  }

  if (!editing) {
    return (
      <h1
        className="page-head__title"
        title="Double-click to rename"
        tabIndex={0}
        onDoubleClick={() => setOpened(true)}
        // Keyboard equivalents, because a rename reachable only with a mouse
        // would be the one control in this editor that is.
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === "F2") setOpened(true);
        }}
      >
        {value}
      </h1>
    );
  }

  return (
    <span className="page-head__name-edit">
      <input
        className="input page-head__name"
        type="text"
        aria-label={label}
        placeholder={placeholder}
        autoFocus
        readOnly={busy}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onBlur={() => {
          if (reverting.current) {
            reverting.current = false;
            return;
          }
          commit();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            commit();
          } else if (event.key === "Escape") {
            reverting.current = true;
            setText(value);
            setOpened(false);
          }
        }}
      />
      {refused && (
        <span className="page-head__name-error" role="alert">
          {error.message}
        </span>
      )}
    </span>
  );
}
