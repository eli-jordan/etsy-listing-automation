// The Backup section's presentational pieces: the app shell (which can carry a
// backup warning on every page), the Admin page with Backup as its own
// section, and the status, storage and history panels. State and click
// handling live in _prototype.tsx.
import { ArchiveIcon } from "@phosphor-icons/react/dist/csr/Archive";
import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { ArrowRightIcon } from "@phosphor-icons/react/dist/csr/ArrowRight";
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { CircleNotchIcon } from "@phosphor-icons/react/dist/csr/CircleNotch";
import { CloudArrowUpIcon } from "@phosphor-icons/react/dist/csr/CloudArrowUp";
import { FolderIcon } from "@phosphor-icons/react/dist/csr/Folder";
import { GearIcon } from "@phosphor-icons/react/dist/csr/Gear";
import { HardDrivesIcon } from "@phosphor-icons/react/dist/csr/HardDrives";
import { SlidersHorizontalIcon } from "@phosphor-icons/react/dist/csr/SlidersHorizontal";
import { StorefrontIcon } from "@phosphor-icons/react/dist/csr/Storefront";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { XCircleIcon } from "@phosphor-icons/react/dist/csr/XCircle";
import type { ReactNode } from "react";
import { ShellSidebar } from "../../../src/shell/ShellSidebar";
import "../../../src/pages/admin/admin.css";
import "../../../src/pages/admin/settings.css";
import "../admin-settings/_admin.css";
import { PageHead } from "../admin-settings/_parts";
import type { BackupRun, BackupSettings, Destination } from "./_fixtures";
import "./_backup.css";

export type AppPage = "dashboard" | "admin";
export type BackupSub = "overview" | "settings";

function NavIcon({ d }: { d: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      {d}
    </svg>
  );
}

/**
 * The real app shell. A failing backup puts a dot on Admin and a banner at the
 * top of every page except the Backup section, which has its own.
 */
export function BackupShell({
  page,
  warning,
  onGo,
  children,
}: {
  page: AppPage;
  /** One line saying what is wrong, or undefined when backups are healthy. */
  warning?: string;
  onGo: (page: AppPage) => void;
  children: ReactNode;
}) {
  const go = (p: AppPage) => (e: { preventDefault: () => void }) => {
    e.preventDefault();
    onGo(p);
  };
  return (
    <div className="shell adm-shell">
      <ShellSidebar shopName="NaturallyInkedStudio">
        <nav className="sidebar__nav" aria-label="App navigation">
          <a className={`nav-item${page === "dashboard" ? " nav-item--active" : ""}`} href="#dashboard" onClick={go("dashboard")}>
            <NavIcon d={<><rect x="3" y="3" width="7.5" height="7.5" rx="1.5" /><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5" /><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5" /><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5" /></>} />
            Dashboard
          </a>
          <a className="nav-item" href="#listings">
            <NavIcon d={<><line x1="8.5" y1="6" x2="20" y2="6" /><line x1="8.5" y1="12" x2="20" y2="12" /><line x1="8.5" y1="18" x2="20" y2="18" /><circle cx="4.5" cy="6" r="1.1" fill="currentColor" stroke="none" /><circle cx="4.5" cy="12" r="1.1" fill="currentColor" stroke="none" /><circle cx="4.5" cy="18" r="1.1" fill="currentColor" stroke="none" /></>} />
            Listings
          </a>
          <a className="nav-item" href="#listing-templates">
            <NavIcon d={<><path d="M12 3 3 8l9 5 9-5-9-5Z" /><path d="m3 13 9 5 9-5" /></>} />
            Listing Templates
          </a>
          <a className="nav-item" href="#templates">
            <NavIcon d={<><rect x="7.5" y="7.5" width="13.5" height="13.5" rx="2" /><path d="M3.5 15.5v-10a2 2 0 0 1 2-2h10" /></>} />
            Mockup Templates
          </a>
        </nav>
        <div className="sidebar__bottom adm-bottom">
          <a
            className={`nav-item${page === "admin" ? " nav-item--active" : ""}`}
            href="#admin"
            aria-current={page === "admin" ? "page" : undefined}
            onClick={go("admin")}
          >
            <GearIcon size={18} />
            Admin
            {warning && <span className="bk-nav-dot" role="img" aria-label="Backups need attention" />}
          </a>
        </div>
      </ShellSidebar>
      <main className="shell__main">
        {warning && page !== "admin" && (
          <div className="adm-warn bk-global" role="alert">
            <WarningIcon size={18} weight="fill" />
            <span>
              <strong>Backups need attention.</strong> {warning}
            </span>
            <button type="button" className="btn btn-secondary bk-banner__btn" onClick={() => onGo("admin")}>
              Open Backup
            </button>
          </div>
        )}
        {children}
      </main>
    </div>
  );
}

/** The Admin page with Backup as its own section beside Shop and Settings. */
export function BackupPage({
  sub,
  on,
  warn,
  interval,
  onSub,
  children,
}: {
  /** Which Backup subsection is open; undefined while backups aren't set up. */
  sub?: BackupSub;
  on: boolean;
  warn: boolean;
  interval: number;
  onSub: (sub: BackupSub) => void;
  children: ReactNode;
}) {
  return (
    <div className="adm-page">
      <PageHead />
      <div className="adm-body">
        <AdminNav sub={sub} on={on} warn={warn} interval={interval} onSub={onSub} />
        <div className="settings-panels">{children}</div>
      </div>
    </div>
  );
}

function AdminNav({
  sub,
  on,
  warn,
  interval,
  onSub,
}: {
  sub?: BackupSub;
  on: boolean;
  warn: boolean;
  interval: number;
  onSub: (sub: BackupSub) => void;
}) {
  const subLink = (id: BackupSub, label: string) => (
    <a
      href={`#backup-${id}`}
      className={`s-subnav__item${sub === id ? " is-active" : ""}`}
      aria-current={sub === id ? "page" : undefined}
      onClick={(e) => {
        e.preventDefault();
        onSub(id);
      }}
    >
      {label}
    </a>
  );
  return (
    <nav className="adm-sections adm-sections--described" aria-label="Admin sections">
      <a href="#shop" className="adm-sections__item">
        <span className="adm-sections__icon">
          <StorefrontIcon size={18} />
        </span>
        <span className="adm-sections__text">
          <span className="adm-sections__label">Shop</span>
          <span className="adm-sections__hint">shop.yaml</span>
        </span>
      </a>
      <div className="s-subnav">
        <a href="#connected" className="s-subnav__item">Connected shops</a>
        <a href="#defaults" className="s-subnav__item">Listing defaults</a>
      </div>
      <a href="#settings" className="adm-sections__item">
        <span className="adm-sections__icon">
          <SlidersHorizontalIcon size={18} />
        </span>
        <span className="adm-sections__text">
          <span className="adm-sections__label">Settings</span>
          <span className="adm-sections__hint">settings.yaml</span>
        </span>
      </a>
      <div className="s-subnav">
        <a href="#ai" className="s-subnav__item">AI</a>
        <a href="#rendering" className="s-subnav__item">Template rendering</a>
      </div>
      <a
        href="#backup"
        className="adm-sections__item adm-sections__item--active"
        onClick={(e) => {
          e.preventDefault();
          if (on) onSub("overview");
        }}
      >
        <span className="adm-sections__icon">
          <ArchiveIcon size={18} />
        </span>
        <span className="adm-sections__text">
          <span className="adm-sections__label">Backup</span>
          <span className="adm-sections__hint">{on ? everyLabel(interval).toLowerCase() : "off"}</span>
        </span>
        {warn && (
          <span className="bk-nav-warn" role="img" aria-label="Needs attention">
            <WarningIcon size={16} weight="fill" />
          </span>
        )}
      </a>
      {on && (
        <div className="s-subnav">
          {subLink("overview", "Status and history")}
          {subLink("settings", "Settings")}
        </div>
      )}
    </nav>
  );
}

export function Panel({
  id,
  title,
  lede,
  aside,
  children,
}: {
  id: string;
  title: string;
  lede?: ReactNode;
  aside?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="b-panel" aria-labelledby={id}>
      <div className="b-panel__head">
        <div>
          <h2 className="b-panel__title" id={id}>
            {title}
          </h2>
          {lede && <p className="b-panel__lede">{lede}</p>}
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** The one-line health summary at the top of the section. */
export function StatusPanel({
  tone,
  headline,
  detail,
  running,
  restoreBusy,
  onBackup,
  onRestore,
  children,
}: {
  tone: "ok" | "warn";
  headline: string;
  detail: string;
  running?: string;
  restoreBusy?: boolean;
  onBackup: () => void;
  onRestore: () => void;
  /** A restore running in the background shows here. */
  children?: ReactNode;
}) {
  return (
    <section className={`b-panel bk-status bk-status--${tone}`} aria-labelledby="bk-status">
      <span className="bk-status__icon" aria-hidden="true">
        {tone === "ok" ? <CheckCircleIcon size={26} weight="fill" /> : <WarningIcon size={26} weight="fill" />}
      </span>
      <div className="bk-status__text">
        <h2 className="b-panel__title" id="bk-status">
          {headline}
        </h2>
        <p className="b-panel__lede">{detail}</p>
        {running && (
          <p className="bk-status__running" role="status">
            <CircleNotchIcon size={14} className="adm-spin" /> {running}
          </p>
        )}
      </div>
      <div className="bk-status__actions">
        <button type="button" className="btn btn-secondary" disabled={restoreBusy} onClick={onRestore}>
          <ArrowCounterClockwiseIcon size={16} /> Restore…
        </button>
        <button type="button" className="btn btn-primary" disabled={running !== undefined} onClick={onBackup}>
          {running ? "Backing up…" : "Back up now"}
        </button>
      </div>
      {children && <div className="bk-status__extra">{children}</div>}
    </section>
  );
}

/** A progress bar with a real fill. */
export function Progress({ value, label }: { value: number; label: string }) {
  return (
    <span
      className="bk-bar"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value * 100)}
    >
      <span className="bk-bar__fill" style={{ width: `${Math.max(2, value * 100)}%` }} />
    </span>
  );
}

export interface StoreFacts {
  /** e.g. "20.1 GB · 5,142 files". */
  workspace: string;
  /** e.g. "23.4 GB for 7 backups". */
  stored: string;
  storedState: { ok: boolean; text: string };
  copyState: (d: Destination) => { ok: boolean; text: string; copied: string };
}

/**
 * Where the data lives, as the three places it passes through. The second
 * arrow is the part people ask about: the app copies new files from the backup
 * storage folder into each destination folder, and the sync client (iCloud for
 * Windows, or a NAS share) takes it from there.
 */
export function StoragePipeline({
  settings,
  facts,
  onSettings,
}: {
  settings: BackupSettings;
  facts: StoreFacts;
  onSettings: () => void;
}) {
  return (
    <Panel
      id="bk-where"
      title="Where your backups are"
      lede="Two steps after every backup. Nothing here ever edits or replaces a file in a destination, so iCloud has nothing to rename."
      aside={
        <button type="button" className="btn btn-secondary" onClick={onSettings}>
          Settings
        </button>
      }
    >
      <ol className="bk-flow">
        <li className="bk-node">
          <span className="bk-node__head">
            <FolderIcon size={18} /> Workspace
          </span>
          <span className="s-mono bk-node__path" title="C:\Users\Admin\naturally-inked-studio-workspace">
            naturally-inked-studio-workspace
          </span>
          <span className="bk-sub">{facts.workspace}. The files the app works on.</span>
        </li>
        <li className="bk-arrow" aria-label={`Step 1: back up, ${everyLabel(settings.intervalHours).toLowerCase()}`}>
          <span className="bk-arrow__step">1</span>
          <span className="bk-arrow__text">
            <strong>Back up</strong>
            <span>{everyLabel(settings.intervalHours)}. Only changes are stored, encrypted.</span>
          </span>
          <ArrowRightIcon size={18} className="bk-arrow__icon" />
        </li>
        <li className="bk-node">
          <span className="bk-node__head">
            <HardDrivesIcon size={18} /> Backup storage folder
          </span>
          <span className="s-mono bk-node__path" title={settings.repository}>
            {settings.repository.split("\\").pop()}
          </span>
          <span className="bk-sub">{facts.stored}. On this computer. Restores read from here.</span>
          <Pill tone={facts.storedState.ok ? "ok" : "bad"}>{facts.storedState.text}</Pill>
        </li>
        <li className="bk-arrow" aria-label="Step 2: copy new files one way">
          <span className="bk-arrow__step">2</span>
          <span className="bk-arrow__text">
            <strong>Copy</strong>
            <span>New files only, one way. Removed when they expire.</span>
          </span>
          <ArrowRightIcon size={18} className="bk-arrow__icon" />
        </li>
        <li className="bk-dests">
          {settings.destinations.length === 0 && (
            <span className="bk-node bk-node--empty bk-sub">No destinations. A failed disk loses the backups too.</span>
          )}
          {settings.destinations.map((d) => {
            const s = facts.copyState(d);
            return (
              <span className="bk-node" key={d.id}>
                <span className="bk-node__head">
                  <CloudArrowUpIcon size={18} /> {d.name}
                </span>
                <span className="s-mono bk-node__path" title={d.path}>
                  {d.path.split("\\").slice(-2).join("\\")}
                </span>
                <span className="bk-sub">
                  Copied {s.copied}. {d.name === "iCloud Drive" ? "iCloud for Windows uploads it from here." : "A complete copy."}
                </span>
                <Pill tone={s.ok ? "ok" : "warn"}>{s.text}</Pill>
              </span>
            );
          })}
        </li>
      </ol>
    </Panel>
  );
}

export function everyLabel(hours: number): string {
  if (hours === 24) return "Every day";
  if (hours % 24 === 0) return `Every ${hours / 24} days`;
  return `Every ${hours} hours`;
}

export function Pill({ tone, children }: { tone: "ok" | "warn" | "bad" | "quiet"; children: ReactNode }) {
  return <span className={`bk-pill bk-pill--${tone}`}>{children}</span>;
}

const RESULT: Record<BackupRun["result"], { label: string; tone: "ok" | "warn" | "bad"; icon: ReactNode }> = {
  ok: { label: "Backed up", tone: "ok", icon: <CheckCircleIcon size={16} weight="fill" /> },
  partial: { label: "Not copied", tone: "warn", icon: <WarningIcon size={16} weight="fill" /> },
  failed: { label: "Failed", tone: "bad", icon: <XCircleIcon size={16} weight="fill" /> },
};

const KEPT: Record<NonNullable<BackupRun["kept"]>, string> = {
  recent: "Recent",
  weekly: "Weekly",
  monthly: "Monthly",
};

/** Every run, newest first. A row with a snapshot can be restored from. */
export function History({
  list,
  settings,
  fresh,
  restoreBusy,
  onRestore,
}: {
  list: BackupRun[];
  settings: BackupSettings;
  /** The run that just finished, briefly highlighted. */
  fresh?: string;
  restoreBusy?: boolean;
  onRestore: (run: BackupRun) => void;
}) {
  return (
    <Panel
      id="bk-history"
      title="Backup history"
      lede={`Every backup from the last ${settings.keepDays} days, then the latest of each week for ${settings.keepWeeks} weeks and of each month for ${settings.keepMonths} months.`}
    >
      <table className="bk-table">
        <colgroup>
          <col className="bk-c-when" />
          <col />
          <col className="bk-c-num" />
          <col className="bk-c-kept" />
          <col className="bk-c-act" />
        </colgroup>
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">Result</th>
            <th scope="col" className="bk-num">Added</th>
            <th scope="col">Kept as</th>
            <th scope="col" aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {list.map((run) => {
            const r = RESULT[run.result];
            return (
              <tr key={run.id} className={`bk-run bk-run--${run.result}${run.id === fresh ? " bk-run--fresh" : ""}`}>
                <td>
                  <span className="bk-when">{run.when}</span>
                  <span className="bk-sub">
                    {run.ago}
                    {run.duration !== "—" && ` · took ${run.duration}`}
                  </span>
                </td>
                <td>
                  <span className={`bk-result bk-result--${r.tone}`}>
                    {r.icon} {r.label}
                  </span>
                  <span className="bk-sub bk-detail">{run.detail}</span>
                </td>
                <td className="bk-num">{run.added}</td>
                <td>{run.kept ? <Pill tone="quiet">{KEPT[run.kept]}</Pill> : <span className="bk-sub">Nothing saved</span>}</td>
                <td className="bk-actions">
                  {run.snapshot && (
                    <button type="button" className="btn btn-ghost bk-restore" disabled={restoreBusy} onClick={() => onRestore(run)}>
                      Restore…
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Panel>
  );
}
