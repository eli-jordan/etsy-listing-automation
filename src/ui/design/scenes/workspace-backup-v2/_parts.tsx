// The Backup section's presentational pieces: the Admin page around it, with
// Settings gaining a third subsection, plus the status, history and
// destination panels. State and click handling live in _prototype.tsx.
import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { CircleNotchIcon } from "@phosphor-icons/react/dist/csr/CircleNotch";
import { CloudArrowUpIcon } from "@phosphor-icons/react/dist/csr/CloudArrowUp";
import { HardDrivesIcon } from "@phosphor-icons/react/dist/csr/HardDrives";
import { SlidersHorizontalIcon } from "@phosphor-icons/react/dist/csr/SlidersHorizontal";
import { StorefrontIcon } from "@phosphor-icons/react/dist/csr/Storefront";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { XCircleIcon } from "@phosphor-icons/react/dist/csr/XCircle";
import type { ReactNode } from "react";
import "../../../src/pages/admin/admin.css";
import "../../../src/pages/admin/settings.css";
import { PageHead } from "../admin-settings/_parts";
import type { BackupRun, BackupSettings, Destination } from "./_fixtures";
import "./_backup.css";

/** The shipped Admin page, Settings open on its new Backup subsection. */
export function BackupPage({ children }: { children: ReactNode }) {
  return (
    <div className="adm-page">
      <PageHead />
      <div className="adm-body">
        <AdminNav />
        <div className="settings-panels">{children}</div>
      </div>
    </div>
  );
}

function AdminNav() {
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
      <a href="#settings" className="adm-sections__item adm-sections__item--active">
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
        <a href="#backup" className="s-subnav__item is-active" aria-current="page">
          Backup
        </a>
      </div>
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
  onBackup,
  onRestore,
}: {
  tone: "ok" | "warn";
  headline: string;
  detail: string;
  running?: string;
  onBackup: () => void;
  onRestore: () => void;
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
        <button type="button" className="btn btn-secondary" onClick={onRestore}>
          <ArrowCounterClockwiseIcon size={16} /> Restore…
        </button>
        <button type="button" className="btn btn-primary" disabled={running !== undefined} onClick={onBackup}>
          {running ? "Backing up…" : "Back up now"}
        </button>
      </div>
    </section>
  );
}

export function WhereStored({
  settings,
  repositoryChecked,
  copyState,
  onEdit,
}: {
  settings: BackupSettings;
  repositoryChecked: string;
  copyState: (d: Destination) => { copied: string; ok: boolean; problem?: string };
  onEdit: () => void;
}) {
  return (
    <Panel
      id="bk-where"
      title="Where backups go"
      lede="Backups run on this computer first, then copy one way to each destination. A destination is never written to except to add new backup files or remove expired ones."
      aside={
        <button type="button" className="btn btn-secondary" onClick={onEdit}>
          Edit settings
        </button>
      }
    >
      <div className="sa-table">
        <div className="sa-row bk-dest">
          <HardDrivesIcon size={18} />
          <span className="sa-row__label">This computer</span>
          <span className="sa-row__value">
            <span className="s-mono">{settings.repository}</span>
            <span className="bk-sub">
              {everyLabel(settings.intervalHours)} · checked weekly, {repositoryChecked}
            </span>
          </span>
          <Pill tone="ok">Up to date</Pill>
        </div>
        {settings.destinations.map((d) => {
          const s = copyState(d);
          return (
            <div className="sa-row bk-dest" key={d.id}>
              <CloudArrowUpIcon size={18} />
              <span className="sa-row__label">{d.name}</span>
              <span className="sa-row__value">
                <span className="s-mono">{d.path}</span>
                <span className="bk-sub">
                  Last copied {s.copied} · {d.checked}
                </span>
              </span>
              {s.ok ? <Pill tone="ok">Up to date</Pill> : <Pill tone="warn">{s.problem ?? "Behind"}</Pill>}
            </div>
          );
        })}
      </div>
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
  onRestore,
}: {
  list: BackupRun[];
  settings: BackupSettings;
  /** The run that just finished, briefly highlighted. */
  fresh?: string;
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
                    <button type="button" className="btn btn-ghost bk-restore" onClick={() => onRestore(run)}>
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
