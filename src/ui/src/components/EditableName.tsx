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
  onCommit: (next: string) => void;
  error?: NameRefusal | null;
  busy?: boolean;
  placeholder?: string;
  label?: string;
  /** Each keystroke, so a design-derived name can leave a part-typed one alone. */
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
