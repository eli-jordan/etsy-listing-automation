import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { useEffect, useRef } from "react";
import { useBackupStatus } from "../../shell/backupStatus";
import type { BackupPage } from "./backup/BackupSection";
import { address, BACKUP_PAGES, type Section, SECTION_LABELS, SECTIONS } from "./adminSections";

/**
 * Admin's sections on a phone: one sticky row of chips that scrolls
 * sideways, in place of the desktop's stacked list, which would fill the
 * first screen before any setting. The current chip is kept in view, and
 * Backup's two pages sit under the row while Backup is open.
 */

type Pick = (section: Section, page?: BackupPage) => void;

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** A new section starts at its top, under the chips. */
function toTop() {
  window.scrollTo({ top: 0 });
}

function Chip({
  id,
  current,
  backupOn,
  backupWarn,
  onPick,
}: {
  id: Section;
  current: boolean;
  backupOn: boolean;
  backupWarn: boolean;
  onPick: Pick;
}) {
  const backup = id === "backup";
  return (
    <a
      href={address(id)}
      className={current ? "adm-chip is-active" : "adm-chip"}
      aria-current={current ? "page" : undefined}
      onClick={(event) => {
        event.preventDefault();
        onPick(id);
        toTop();
      }}
    >
      {SECTION_LABELS[id]}
      {backup && !backupOn && <span className="adm-chip__hint">off</span>}
      {backup && backupWarn && (
        <span className="adm-chip__warn" role="img" aria-label="Needs attention">
          <WarningIcon size={14} weight="fill" />
        </span>
      )}
    </a>
  );
}

export function PhoneSections({
  section,
  backupPage,
  onPick,
}: {
  section: Section;
  backupPage: BackupPage;
  onPick: Pick;
}) {
  const { view } = useBackupStatus();
  const on = view.state === "on";
  const row = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const strip = row.current;
    const chip = strip?.querySelector<HTMLElement>("[aria-current='page']");
    if (!strip || !chip || typeof strip.scrollTo !== "function") return;
    strip.scrollTo({
      left: chip.offsetLeft - (strip.clientWidth - chip.offsetWidth) / 2,
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
  }, [section]);

  return (
    <nav className="adm-chips" aria-label="Admin sections">
      <div ref={row} className="adm-chips__row">
        {SECTIONS.map((id) => (
          <Chip
            key={id}
            id={id}
            current={id === section}
            backupOn={on}
            backupWarn={view.banner !== null}
            onPick={onPick}
          />
        ))}
      </div>
      {section === "backup" && on && (
        <div className="adm-chips__pages">
          {BACKUP_PAGES.map(([page, label]) => (
            <a
              key={page}
              href={address("backup", page)}
              className={backupPage === page ? "adm-chips__page is-active" : "adm-chips__page"}
              aria-current={backupPage === page ? "page" : undefined}
              onClick={(event) => {
                event.preventDefault();
                onPick("backup", page);
              }}
            >
              {label}
            </a>
          ))}
        </div>
      )}
    </nav>
  );
}
