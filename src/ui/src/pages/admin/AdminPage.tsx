import { ArchiveIcon } from "@phosphor-icons/react/dist/csr/Archive";
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { CircleNotchIcon } from "@phosphor-icons/react/dist/csr/CircleNotch";
import { SlidersHorizontalIcon } from "@phosphor-icons/react/dist/csr/SlidersHorizontal";
import { StorefrontIcon } from "@phosphor-icons/react/dist/csr/Storefront";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { type MouseEvent, type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getShopConnections, type ShopConnections } from "../../api/shop";
import { bannerWarnings, useBackupStatus } from "../../shell/backupStatus";
import type { BackupPage } from "./backup/BackupSection";
import { ConnectedShops } from "./ConnectedShops";
import { CurrencyDialog } from "./CurrencyDialog";
import type { InfoState } from "./Info";
import { ListingDefaults } from "./ListingDefaults";
import { type SettingsSection, SettingsPanel } from "./SettingsPanel";
import { useShopLookups } from "./useShopLookups";
import { type SaveStatus, useShopSettings } from "./useShopSettings";
import "./admin.css";

type Section = "connected" | "defaults" | SettingsSection;
const SECTIONS: readonly Section[] = ["connected", "defaults", "ai", "rendering", "backup"];
const isSettings = (section: Section): section is SettingsSection =>
  section === "ai" || section === "rendering" || section === "backup";

/** `/admin?section=backup&page=setup`: the address of a section, so a link
 * (the backup banner's Open Backup) can open it. Connected shops is bare. */
function address(section: Section, page?: BackupPage): string {
  if (section === "connected") return "?";
  return page === "setup" ? `?section=${section}&page=setup` : `?section=${section}`;
}

/**
 * `/admin` (Admin plan, PR 3): the Shop tab's Connected shops and Listing
 * defaults, from the approved `admin-shop` prototype. Both panels stay
 * mounted so switching never discards a pending edit. Settings owns a
 * separate file/save queue; its AI, Template rendering (template positions
 * PR 5) and Backup (workspace-backup PR 6) subsections share it, and opening
 * Settings selects AI. The section is in the address (`address`).
 */
export function AdminPage() {
  const [params, setParams] = useSearchParams();
  const named = params.get("section") as Section | null;
  const section: Section = named && SECTIONS.includes(named) ? named : "connected";
  const backupPage: BackupPage = params.get("page") === "setup" ? "setup" : "status";
  const pick = (next: Section, page?: BackupPage) =>
    setParams(new URLSearchParams(address(next, page)));
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
  }, [setCurrencyOpen]);

  const { shop, save } = settings;
  const changeCurrency = async (code: string) => {
    // The dialog shows its own failure and retries only through its
    // acknowledged Change, so a cancelled change is never resent by Retry.
    const outcome = await save({ currency: code }, { retain: false });
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
          {!isSettings(section) && (
            <SaveIndicator status={settings.status} onRetry={() => void settings.retry()} />
          )}
        </div>
      </div>
      {!isSettings(section) && settings.status.kind === "conflict" && (
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
        <Nav section={section} backupPage={backupPage} onPick={pick} />
        <div>
          {!isSettings(section) && settings.loadError !== null && (
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
                key={settings.loadedVersion}
                shop={shop}
                pending={settings.pending}
                save={save}
                discard={settings.discard}
                refusal={settings.refusal}
                fieldErrors={settings.fieldErrors}
                locked={settings.locked}
                lookups={lookups}
                info={info}
              />
            )}
          </div>
          <div hidden={!isSettings(section)}>
            <SettingsPanel
              section={isSettings(section) ? section : "ai"}
              backupPage={backupPage}
              onBackupPage={(page) => pick("backup", page)}
            />
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

function SaveIndicator({ status, onRetry }: { status: SaveStatus; onRetry: () => void }) {
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
      <>
        <span className="adm-save adm-save--error" role="status">
          <WarningIcon size={14} /> {status.message}
        </span>
        <button type="button" className="btn btn-secondary" onClick={onRetry}>
          Retry save
        </button>
      </>
    );
  return <span role="status" />;
}

function Nav({
  section,
  backupPage,
  onPick,
}: {
  section: Section;
  backupPage: BackupPage;
  onPick: (s: Section, page?: BackupPage) => void;
}) {
  const { status } = useBackupStatus();
  const on = status?.enabled ?? false;
  const warn = bannerWarnings(status).length > 0;
  const inBackup = section === "backup";
  const sub: { id: Section; label: string }[] = [
    { id: "connected", label: "Connected shops" },
    { id: "defaults", label: "Listing defaults" },
  ];
  return (
    <nav className="adm-sections adm-sections--described" aria-label="Admin sections">
      <a
        href={address("connected")}
        className={`adm-sections__item${!isSettings(section) ? " adm-sections__item--active" : ""}`}
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
      <SubNav items={sub} section={section} onPick={onPick} />
      <a
        href={address("ai")}
        className={`adm-sections__item${isSettings(section) ? " adm-sections__item--active" : ""}`}
        onClick={(event) => {
          event.preventDefault();
          onPick("ai");
        }}
      >
        <span className="adm-sections__icon">
          <SlidersHorizontalIcon size={18} />
        </span>
        <span className="adm-sections__text">
          <span className="adm-sections__label">Settings</span>
          <span className="adm-sections__hint">settings.yaml</span>
        </span>
      </a>
      <SubNav
        items={[
          { id: "ai", label: "AI" },
          { id: "rendering", label: "Template rendering" },
        ]}
        section={section}
        onPick={onPick}
      >
        {/* Backup (workspace-backup interactions, *Where Backup lives*): off
            before set-up, then two pages nested beneath it. */}
        <a
          href={address("backup")}
          className={`s-subnav__item bk-subnav-backup${inBackup && !on ? " is-active" : ""}`}
          aria-current={inBackup && !on ? "page" : undefined}
          onClick={(event) => {
            event.preventDefault();
            onPick("backup");
          }}
        >
          <ArchiveIcon size={15} /> Backup
          {!on && <span className="bk-subnav-hint">off</span>}
          {warn && (
            <span className="bk-nav-warn" role="img" aria-label="Needs attention">
              <WarningIcon size={15} weight="fill" />
            </span>
          )}
        </a>
        {on && (
          <div className="s-subnav bk-subnav-nested">
            {BACKUP_PAGES.map(([page, label]) => {
              const current = inBackup && backupPage === page;
              return (
                <a
                  key={page}
                  href={address("backup", page)}
                  className={current ? "s-subnav__item is-active" : "s-subnav__item"}
                  aria-current={current ? "page" : undefined}
                  onClick={(event) => {
                    event.preventDefault();
                    onPick("backup", page);
                  }}
                >
                  {label}
                </a>
              );
            })}
          </div>
        )}
      </SubNav>
    </nav>
  );
}

const BACKUP_PAGES = [
  ["status", "Status and history"],
  ["setup", "Setup"],
] as const;

function SubNav({
  items,
  section,
  onPick,
  children,
}: {
  items: { id: Section; label: string }[];
  section: Section;
  onPick: (s: Section) => void;
  children?: ReactNode;
}) {
  return (
    <div className="s-subnav">
      {items.map((s) => (
        <a
          key={s.id}
          href={address(s.id)}
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
      {children}
    </div>
  );
}
