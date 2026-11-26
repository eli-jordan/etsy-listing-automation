import { useRef, useState } from "react";
import { useIsPhone } from "../phone/usePhone";

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
  busy?: boolean;
  placeholder?: string;
  label?: string;
  /** What is in the field right now, as it is typed. A listing that has no
   * name yet can be given one by something other than this field (design-derived names,
   * where picking a design names a draft), and that must not overwrite a name
   * the seller is part-way through typing -- which `value` cannot show,
   * because an uncommitted name is not the listing's name. */
  onDraftChange?: (text: string) => void;
  as?: "h1" | "span";
  titleClassName?: string;
  inputClassName?: string;
}

export function EditableName({
  value,
  onCommit,
  error = null,
  busy = false,
  placeholder = "Name this listing…",
  label = "Listing name",
  onDraftChange,
  as: Title = "h1",
  titleClassName = "page-head__title",
  inputClassName = "page-head__name",
}: EditableNameProps) {
  const [opened, setOpened] = useState(false);
  const [text, setText] = useState(value);
  const [committed, setCommitted] = useState(value);
  // A blur *caused by* Escape must not commit, and the browser fires blur after
  // the keydown either way -- so the key handler records what it decided and
  // the blur handler obeys it.
  const reverting = useRef(false);
  const isPhone = useIsPhone();

  // Adjusting state while rendering, rather than in an effect: the name landed
  // (a rename went through, or this page moved to another listing) and the edit
  // buffer is about the old one.
  if (committed !== value) {
    setCommitted(value);
    setText(value);
    setOpened(false);
  }

  const unnamed = value === "";
  const refused = error !== null && text.trim() === error.name;
  const editing = opened || unnamed || refused;

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
      <Title
        className={titleClassName}
        title={isPhone ? "Tap to rename" : "Double-click to rename"}
        tabIndex={0}
        onDoubleClick={() => setOpened(true)}
        onClick={isPhone ? () => setOpened(true) : undefined}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === "F2") setOpened(true);
        }}
      >
        {value}
        {isPhone && <span className="editable-name__pencil" aria-hidden="true" />}
      </Title>
    );
  }

  return (
    <span className="page-head__name-edit">
      <input
        className={`input ${inputClassName}`}
        type="text"
        aria-label={label}
        placeholder={placeholder}
        autoFocus
        readOnly={busy}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          onDraftChange?.(event.target.value);
        }}
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
