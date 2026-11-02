// Shop-tab pieces shared by the three directions: the danger tag, the info
// button and the info card it opens. Page head, section list and controls come
// from the first Admin round.
import { SlidersHorizontalIcon } from "@phosphor-icons/react/dist/csr/SlidersHorizontal";
import { StorefrontIcon } from "@phosphor-icons/react/dist/csr/Storefront";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { WarningOctagonIcon } from "@phosphor-icons/react/dist/csr/WarningOctagon";
import type { CSSProperties } from "react";
import { info } from "./_fixtures";

export { PageHead, SaveStatus, SectionList, Select, StatusDot, Switch } from "../admin-settings/_parts";

export function DangerTag({ text = "Danger zone" }: { text?: string }) {
  return (
    <span className="s-danger-tag">
      <WarningOctagonIcon size={13} weight="bold" /> {text}
    </span>
  );
}

export function InfoButton({ field, open }: { field: string; open?: boolean }) {
  return (
    <button
      type="button"
      className={open ? "s-info-btn is-open" : "s-info-btn"}
      aria-label={`About ${info[field].title}`}
      aria-expanded={open}
    >
      <InfoIcon size={15} weight={open ? "fill" : "regular"} />
    </button>
  );
}

/** One field's explanation: what it is, what changing it does, where it lives. */
export function InfoCard({
  field,
  variant = "card",
  style,
}: {
  field: string;
  variant?: "card" | "popover" | "inline" | "panel";
  style?: CSSProperties;
}) {
  const i = info[field];
  return (
    <div className={`s-info s-info--${variant}`} style={style} role={variant === "popover" ? "dialog" : undefined}>
      {variant !== "inline" && <p className="s-info__title">{i.title}</p>}
      <p className="s-info__what">{i.what}</p>
      <p className="s-info__effect">
        <strong>If you change it: </strong>
        {i.effect}
      </p>
      <p className="s-info__source">{i.source}</p>
    </div>
  );
}

/** Direction B's described section list, with Shop split into its two sections. */
export function ShopNav({ active, dir }: { active: "connected" | "defaults"; dir: string }) {
  const sub = [
    { id: "connected", label: "Connected shops" },
    { id: "defaults", label: "Listing defaults" },
  ] as const;
  return (
    <nav className="adm-sections adm-sections--described" aria-label="Admin sections">
      <a href="#shop" className="adm-sections__item adm-sections__item--active" data-goto={`admin-shop/connected/${dir}`}>
        <span className="adm-sections__icon">
          <StorefrontIcon size={18} />
        </span>
        <span className="adm-sections__text">
          <span className="adm-sections__label">Shop</span>
          <span className="adm-sections__hint">shop.yaml</span>
        </span>
      </a>
      <div className="s-subnav">
        {sub.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            data-goto={`admin-shop/${s.id}/${dir}`}
            className={s.id === active ? "s-subnav__item is-active" : "s-subnav__item"}
            aria-current={s.id === active ? "page" : undefined}
          >
            {s.label}
          </a>
        ))}
      </div>
      <a href="#settings" className="adm-sections__item" data-goto="admin-settings/settings/b-cards">
        <span className="adm-sections__icon">
          <SlidersHorizontalIcon size={18} />
        </span>
        <span className="adm-sections__text">
          <span className="adm-sections__label">Settings</span>
          <span className="adm-sections__hint">settings.yaml</span>
        </span>
      </a>
    </nav>
  );
}
