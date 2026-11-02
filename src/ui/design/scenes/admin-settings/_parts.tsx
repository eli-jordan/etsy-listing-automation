// Small pieces every Admin direction shares: the page head, the section list,
// the blur-save status, and form controls in the app's own classes.
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { CircleNotchIcon } from "@phosphor-icons/react/dist/csr/CircleNotch";
import { SlidersHorizontalIcon } from "@phosphor-icons/react/dist/csr/SlidersHorizontal";
import { StorefrontIcon } from "@phosphor-icons/react/dist/csr/Storefront";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import type { ReactNode } from "react";

export type Section = "shop" | "settings";

export function PageHead({ children }: { children?: ReactNode }) {
  return (
    <div className="page-head">
      <h1 className="page-head__title">Admin</h1>
      <span className="page-head__meta">Changes save when you leave a field</span>
      {children && <div className="page-head__actions">{children}</div>}
    </div>
  );
}

const SECTIONS: { id: Section; label: string; hint: string; icon: ReactNode }[] = [
  { id: "shop", label: "Shop", hint: "shop.yaml", icon: <StorefrontIcon size={18} /> },
  { id: "settings", label: "Settings", hint: "settings.yaml", icon: <SlidersHorizontalIcon size={18} /> },
];

export function SectionList({
  active,
  variant,
  goto,
}: {
  active: Section;
  variant: "plain" | "described" | "compact";
  goto: (s: Section) => string;
}) {
  return (
    <nav className={`adm-sections adm-sections--${variant}`} aria-label="Admin sections">
      {SECTIONS.map((s) => (
        <a
          key={s.id}
          href={`#${s.id}`}
          data-goto={goto(s.id)}
          className={s.id === active ? "adm-sections__item adm-sections__item--active" : "adm-sections__item"}
          aria-current={s.id === active ? "page" : undefined}
        >
          {variant !== "plain" && <span className="adm-sections__icon">{s.icon}</span>}
          <span className="adm-sections__text">
            <span className="adm-sections__label">{s.label}</span>
            {variant === "described" && <span className="adm-sections__hint">{s.hint}</span>}
          </span>
        </a>
      ))}
    </nav>
  );
}

export function SaveStatus({ state, text }: { state: "saved" | "saving" | "error"; text?: string }) {
  if (state === "saving")
    return (
      <span className="adm-save adm-save--saving">
        <CircleNotchIcon size={14} className="adm-spin" /> Saving…
      </span>
    );
  if (state === "error")
    return (
      <span className="adm-save adm-save--error">
        <WarningIcon size={14} /> {text ?? "Not saved"}
      </span>
    );
  return (
    <span className="adm-save adm-save--ok">
      <CheckCircleIcon size={14} /> {text ?? "Saved"}
    </span>
  );
}

export function Switch({ on, label }: { on: boolean; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} className={on ? "switch switch--on" : "switch"}>
      <span className="switch__knob" />
    </button>
  );
}

export function Select({
  value,
  options,
  label,
  invalid,
  disabled,
}: {
  value: string;
  options: { id: string; label: string }[] | string[];
  label: string;
  invalid?: boolean;
  disabled?: boolean;
}) {
  const opts = options.map((o) => (typeof o === "string" ? { id: o, label: o } : o));
  const known = opts.some((o) => o.id === value);
  return (
    <select
      aria-label={label}
      defaultValue={value}
      disabled={disabled}
      className={invalid ? "adm-select adm-select--invalid" : "adm-select"}
    >
      {!known && <option value={value}>{value} (not offered)</option>}
      {opts.map((o) => (
        <option key={o.id} value={o.id}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function StatusDot({ status, text }: { status: "ready" | "signed-out" | "missing"; text: string }) {
  return (
    <span className={`adm-dot adm-dot--${status}`}>
      <span className="adm-dot__mark" aria-hidden="true" />
      {text}
    </span>
  );
}
