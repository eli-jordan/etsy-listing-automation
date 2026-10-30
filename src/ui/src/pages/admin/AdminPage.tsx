import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { CircleNotchIcon } from "@phosphor-icons/react/dist/csr/CircleNotch";
import { SlidersHorizontalIcon } from "@phosphor-icons/react/dist/csr/SlidersHorizontal";
import { StorefrontIcon } from "@phosphor-icons/react/dist/csr/Storefront";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { type MouseEvent, useCallback, useEffect, useRef, useState } from "react";
import { getShopConnections, type ShopConnections } from "../../api/shop";
import { ConnectedShops } from "./ConnectedShops";
import { CurrencyDialog } from "./CurrencyDialog";
import type { InfoState } from "./Info";
import { ListingDefaults } from "./ListingDefaults";
import { useShopLookups } from "./useShopLookups";
import { type SaveStatus, useShopSettings } from "./useShopSettings";
import "./admin.css";

type Section = "connected" | "defaults";

/**
 * `/admin` (Admin plan, PR 3): the Shop tab's Connected shops and Listing
 * defaults, from the approved `admin-shop` prototype. The section is page
 * state, not a URL parameter, and both panels stay mounted so switching
 * never discards a pending edit. Settings arrives in a later PR and is shown
 * as unavailable rather than as controls that do nothing.
 */
export function AdminPage() {
  const [section, setSection] = useState<Section>("connected");
  const [openInfo, setOpenInfo] = useState<string | null>(null);
  const [currencyOpen, setCurrencyOpen] = useState(false);
  const [connections, setConnections] = useState<ShopConnections | null>(null);
  const [connectionsError, setConnectionsError] = useState<string | null>(null);
  const currencyButton = useRef<HTMLButtonElement>(null);
  const settings = useShopSettings();
  const lookups = useShopLookups();

  useEffect(() => {
    getShopConnections()
      .then(setConnections)
      .catch((error: unknown) =>
        setConnectionsError(error instanceof Error ? error.message : "could not read the shops"),
      );
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpenInfo(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const info: InfoState = {
    open: openInfo,
    toggle: (field) => setOpenInfo((current) => (current === field ? null : field)),
  };

  // Clicking anywhere but an info button or card closes the open card.
  const onRootClick = (event: MouseEvent) => {
    const target = event.target as HTMLElement;
    if (!target.closest(".s-info-btn") && !target.closest(".s-info")) setOpenInfo(null);
  };

  const closeCurrency = useCallback(() => {
    setCurrencyOpen(false);
    // The trigger is re-rendered enabled by then; focus it after the commit.
    queueMicrotask(() => currencyButton.current?.focus());
  }, []);

  const { shop, save } = settings;
  const changeCurrency = async (code: string) => {
    const outcome = await save({ currency: code });
    if (outcome?.kind === "saved") closeCurrency();
    else if (outcome?.kind === "invalid")
      throw new Error(outcome.fieldErrors.currency ?? outcome.message);
    else if (outcome?.kind === "conflict") closeCurrency();
  };

  return (
    <div className="adm-page" onClick={onRootClick}>
      <div className="page-head">
        <h1 className="page-head__title">Admin</h1>
        <span className="page-head__meta">Changes save when you leave a field</span>
        <div className="page-head__actions">
          <SaveIndicator status={settings.status} />
        </div>
      </div>
      {settings.status.kind === "conflict" && (
        <div className="adm-warn sp-conflict" role="alert">
          <WarningIcon size={18} />
          <span>
            shop.yaml changed on disk since this page loaded it. Nothing was overwritten. Reload it,
            then make your change again.
          </span>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void settings.reload()}
          >
            Reload shop.yaml
          </button>
        </div>
      )}
      <div className="adm-body">
        <Nav section={section} onPick={setSection} />
        <div>
          {settings.loadError !== null && (
            <div className="adm-warn" role="alert">
              <WarningIcon size={18} />
              <span>{settings.loadError}</span>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => void settings.reload()}
              >
                Check file again
              </button>
            </div>
          )}
          <div hidden={section !== "connected"}>
            <ConnectedShops
              shop={shop}
              connections={connections}
              connectionsError={connectionsError}
              info={info}
              locked={settings.locked}
              currencyButton={currencyButton}
              onChangeCurrency={() => setCurrencyOpen(true)}
            />
          </div>
          <div hidden={section !== "defaults"}>
            {shop && (
              <ListingDefaults
                shop={shop}
                save={save}
                fieldErrors={settings.fieldErrors}
                locked={settings.locked}
                lookups={lookups}
                info={info}
              />
            )}
          </div>
        </div>
      </div>
      {currencyOpen && shop && (
        <CurrencyDialog
          current={shop.currency}
          currencies={shop.supported_currencies}
          shopCurrency={connections?.etsy.shop_currency ?? null}
          onCancel={closeCurrency}
          onConfirm={changeCurrency}
        />
      )}
    </div>
  );
}

function SaveIndicator({ status }: { status: SaveStatus }) {
  if (status.kind === "saving")
    return (
      <span className="adm-save adm-save--saving" role="status">
        <CircleNotchIcon size={14} className="adm-spin" /> Saving…
      </span>
    );
  if (status.kind === "saved")
    return (
      <span className="adm-save adm-save--ok" role="status">
        <CheckCircleIcon size={14} /> Saved
      </span>
    );
  if (status.kind === "error")
    return (
      <span className="adm-save adm-save--error" role="status">
        <WarningIcon size={14} /> {status.message}
      </span>
    );
  return <span role="status" />;
}

function Nav({ section, onPick }: { section: Section; onPick: (s: Section) => void }) {
  const sub: { id: Section; label: string }[] = [
    { id: "connected", label: "Connected shops" },
    { id: "defaults", label: "Listing defaults" },
  ];
  return (
    <nav className="adm-sections adm-sections--described" aria-label="Admin sections">
      <a
        href="#shop"
        className="adm-sections__item adm-sections__item--active"
        onClick={(e) => {
          e.preventDefault();
          onPick("connected");
        }}
      >
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
            className={s.id === section ? "s-subnav__item is-active" : "s-subnav__item"}
            aria-current={s.id === section ? "page" : undefined}
            onClick={(e) => {
              e.preventDefault();
              onPick(s.id);
            }}
          >
            {s.label}
          </a>
        ))}
      </div>
      <div className="adm-sections__item adm-sections__item--unavailable" aria-disabled="true">
        <span className="adm-sections__icon">
          <SlidersHorizontalIcon size={18} />
        </span>
        <span className="adm-sections__text">
          <span className="adm-sections__label">Settings</span>
          <span className="adm-sections__hint">settings.yaml · not editable here yet</span>
        </span>
      </div>
    </nav>
  );
}
