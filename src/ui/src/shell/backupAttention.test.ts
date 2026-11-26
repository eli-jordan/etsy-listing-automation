import { describe, expect, it } from "vitest";
import type { BackupStatus, RestoreStatus, RunningBackup } from "../api/backup";
import {
  BACKUP_ICLOUD,
  backupDestination,
  backupsMissing,
  backupsOff,
  backupsOn,
  backupWarning,
} from "../test/backup";
import { type BackupsOn, backupView } from "./backupAttention";

/* Workspace-backup interactions, *Warnings*: which warning tops the banner,
   which action each one offers on Status and history, and what waits while
   something runs. */

const NAS = "//nas/backups/studio";

function on(status: BackupStatus): BackupsOn {
  const view = backupView(status, null);
  if (view.state !== "on") throw new Error(`expected on, got ${view.state}`);
  return view;
}

const changedCopy = backupDestination({
  changed: [{ name: "data/7c/7c41e0d2", expected_size: 16_800_000, actual_size: 16_100_000 }],
  unexpected: ["index/a3f9c2e1 2"],
});

describe("the state of backups", () => {
  it.each([
    ["loading", null, null],
    ["error", null, "Could not reach the server"],
    ["off", backupsOff(), null],
    ["on", backupsOn(), null],
    // A failed read keeps the status it had, so the page keeps drawing it.
    ["on", backupsOn(), "Could not reach the server"],
    ["off", backupsOff(), "Could not reach the server"],
  ] as const)("is %s for status %o and error %o", (state, status, error) => {
    expect(backupView(status, error).state).toBe(state);
  });

  it("carries the read's error only while there is no status", () => {
    expect(backupView(null, "offline")).toMatchObject({ state: "error", error: "offline" });
  });
});

describe("the banner warning", () => {
  it.each([
    ["nothing while loading", backupView(null, null)],
    ["nothing for an unread status", backupView(null, "offline")],
    ["nothing for backups being off", backupView(backupsOff(), null)],
    ["nothing while healthy", backupView(backupsOn(), null)],
  ])("shows %s", (_name, view) => {
    expect(view.banner).toBeNull();
  });

  it("shows the first warning the server sends", () => {
    const stale = backupWarning("stale");
    const view = on(backupsOn({ warnings: [stale, backupWarning("failed")] }));
    expect(view.banner).toBe(stale);
  });

  it("skips a warning kept off the banner", () => {
    const failed = backupWarning("failed");
    const view = on(backupsOn({ warnings: [backupWarning("off"), failed] }));
    expect(view.banner).toBe(failed);
    expect(view.warnings).toEqual([failed]);
  });
});

describe("the actions on Status and history", () => {
  it.each([
    ["stale", { action: "retry" }],
    ["failed", { action: "retry" }],
    ["behind", { action: "retry" }],
    ["repository_missing", { action: "connect" }],
  ] as const)("offers %s the %o action", (kind, expected) => {
    const warning = backupWarning(kind, { destination: BACKUP_ICLOUD });
    expect(on(backupsOn({ warnings: [warning] })).attention).toEqual([
      expected.action === "retry"
        ? { action: "retry", warnings: [warning] }
        : { ...expected, warning },
    ]);
  });

  it("offers a changed copy the repair of that destination", () => {
    const warning = backupWarning("changed", { destination: BACKUP_ICLOUD });
    const view = on(backupsOn({ destinations: [changedCopy], warnings: [warning] }));
    expect(view.attention).toEqual([{ action: "repair", warning, destination: changedCopy }]);
  });

  it("answers every retryable warning with one Try again, after the others", () => {
    const stale = backupWarning("stale");
    const behind = backupWarning("behind", { destination: NAS });
    const iCloud = backupWarning("changed", { destination: BACKUP_ICLOUD });
    const nas = backupWarning("changed", { destination: NAS });
    const nasCopy = backupDestination({ path: NAS, changed: [], unexpected: ["x 2"] });
    const view = on(
      backupsOn({
        destinations: [changedCopy, nasCopy],
        // The server's order: run warnings, then each destination's.
        warnings: [stale, behind, nas, iCloud],
      }),
    );
    expect(view.attention).toEqual([
      { action: "repair", warning: iCloud, destination: changedCopy },
      { action: "repair", warning: nas, destination: nasCopy },
      { action: "retry", warnings: [stale, behind] },
    ]);
  });

  it("puts a missing repository first", () => {
    const missing = backupsMissing();
    const failed = backupWarning("failed");
    const view = on({ ...missing, warnings: [failed, ...missing.warnings] });
    expect(view.attention.map((item) => item.action)).toEqual(["connect", "retry"]);
  });

  it("offers nothing while healthy", () => {
    expect(on(backupsOn()).attention).toEqual([]);
  });
});

describe("each destination's copy", () => {
  it("counts the changed and unexpected files while a warning names it", () => {
    const warning = backupWarning("changed", { destination: BACKUP_ICLOUD });
    const view = on(backupsOn({ destinations: [changedCopy], warnings: [warning] }));
    expect(view.copies).toEqual([{ destination: changedCopy, toCheck: 2 }]);
  });

  it("has nothing to check without that warning, as while the repository is missing", () => {
    // The server sends only repository_missing then, though the state file
    // still records what the last copy found.
    const view = on({ ...backupsMissing(), destinations: [changedCopy] });
    expect(view.copies).toEqual([{ destination: changedCopy, toCheck: 0 }]);
    expect(view.attention.map((item) => item.action)).toEqual(["connect"]);
  });

  it("is unaffected by another destination's warning", () => {
    const nas = backupDestination({ path: NAS });
    const warning = backupWarning("changed", { destination: BACKUP_ICLOUD });
    const view = on(backupsOn({ destinations: [changedCopy, nas], warnings: [warning] }));
    expect(view.copies.map((copy) => copy.toCheck)).toEqual([2, 0]);
  });
});

describe("what runs", () => {
  const running: RunningBackup = {
    operation: "backup",
    started_at: "2026-11-23T10:00:00Z",
    step: "backing_up",
  };
  const restore = (outcome: "running" | "succeeded"): RestoreStatus => ({
    snapshot_id: "b".repeat(64),
    snapshot_time: "2026-11-23T08:00:00Z",
    target: "D:/restored",
    started_at: "2026-11-23T10:00:00Z",
    outcome,
    fraction: 0.5,
  });

  it.each([
    ["nothing while loading", null, false, false],
    ["nothing while idle", backupsOn(), false, false],
    ["a backup", backupsOn({ running }), true, false],
    ["a repair", backupsOn({ running: { ...running, operation: "repair" } }), true, false],
    ["a backup while off", backupsOff({ running }), true, false],
    ["a restore", backupsOn({ restore: restore("running") }), false, true],
    ["nothing after a restore ends", backupsOn({ restore: restore("succeeded") }), false, false],
  ] as const)("names %s", (_name, status, isRunning, restoring) => {
    expect(backupView(status as BackupStatus | null, null)).toMatchObject({
      running: isRunning,
      restoring,
    });
  });
});
