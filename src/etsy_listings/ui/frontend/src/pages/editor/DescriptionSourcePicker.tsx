import { useEffect, useRef, useState } from "react";
import type { CommonCopySummary } from "../../types";

export function DescriptionSourcePicker({
  value,
  items,
  onSelect,
}: {
  value: string | null;
  items: CommonCopySummary[];
  onSelect: (value: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const selected = items.find((item) => item.ref === value);
  const label = value === null ? "Write inline body" : (selected?.title ?? value);
  const term = query.trim().toLowerCase();
  const matches = items.filter((item) =>
    [item.title, item.summary ?? "", item.ref].some((text) => text.toLowerCase().includes(term)),
  );

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function choose(next: string | null) {
    onSelect(next);
    setOpen(false);
    setQuery("");
    trigger.current?.focus();
  }

  return (
    <div className="description-source-picker" ref={root}>
      <button
        id="details-description-source"
        ref={trigger}
        className="input description-source-picker__trigger"
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => {
          setQuery("");
          setOpen(!open);
        }}
      >
        <span>{label}</span>
        <span aria-hidden="true" className="description-source-picker__chevron" />
      </button>
      {open && (
        <div className="description-source-picker__menu">
          <input
            className="input"
            type="search"
            autoFocus
            aria-label="Search description body sources"
            placeholder="Search common copy..."
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setOpen(false);
                trigger.current?.focus();
              }
              if (event.key === "Enter" && matches.length === 1 && matches[0]) {
                event.preventDefault();
                choose(matches[0].ref);
              }
            }}
          />
          <div role="listbox" aria-label="Description body sources">
            <button
              type="button"
              role="option"
              aria-selected={value === null}
              onClick={() => choose(null)}
            >
              Write inline body
            </button>
            {matches.map((item) => (
              <button
                key={item.ref}
                type="button"
                role="option"
                aria-selected={value === item.ref}
                onClick={() => choose(item.ref)}
              >
                <strong>{item.title}</strong>
                {item.summary && <span>{item.summary}</span>}
              </button>
            ))}
            {matches.length === 0 && <p>No matching common copy</p>}
          </div>
        </div>
      )}
    </div>
  );
}
