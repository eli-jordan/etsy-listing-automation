import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, type MockInstance, vi } from "vitest";
import * as backupApi from "../../../api/backup";
import type { HistoryEntry } from "../../../api/backup";
import * as settingsApi from "../../../api/workspaceSettings";
import type { WorkspaceSettings } from "../../../api/workspaceSettings";
import { BackupStatusProvider } from "../../../shell/BackupStatusProvider";
import {
  BACKUP_ICLOUD,
  BACKUP_REPOSITORY,
  backupsOff,
  backupsOn,
  backupsMissing,
  hoursFromNow,
} from "../../../test/backup";
import { AdminPage } from "../AdminPage";

/* Workspace-backup plan, PR 6: Admin › Settings › Backup against a mocked
   HTTP surface (interactions, *Status and history*, *Set up and Setup*,
   *Warnings*, *Changed and unexpected files*). */

const REPO = BACKUP_REPOSITORY;
const ICLOUD = BACKUP_ICLOUD;
const HOUR = 3_600_000;
const PASSPHRASE = ["correct", "horse", "battery"].join("-");
const iso = hoursFromNow;

const weights = { reviews: 100 };
function workspace(backup?: WorkspaceSettings["backup"]): WorkspaceSettings {
  return {
    revision: "s1",
    template_positions: { scale: { min: 0.8, max: 1.1 }, offset: 0.1, rotation: 15 },
    concurrency: 1,
    providers: [{ name: "codex", enabled: true }],
    weights,
    default_weights: weights,
    step_limit_minutes: 5,
    run_limit_minutes: 20,
    ...(backup && { backup }),
  };
}

const SAVED_BLOCK = {
  repository: REPO,
  destinations: [ICLOUD],
  interval_hours: 12 as const,
  retention: { keep_within_days: 7, weekly: 4, monthly: 3 },
};

const OFF = backupsOff();
const healthy = backupsOn;

function run(startedHoursAgo: number, extra: Partial<HistoryEntry["run"]> = {}): HistoryEntry {
  return {
    kept_as: "recent",
    run: {
      started_at: iso(-startedHoursAgo),
      finished_at: new Date(Date.now() - startedHoursAgo * HOUR + 48_000).toISOString(),
      outcome: "succeeded",
      repository: REPO,
      snapshot_id: "a3f9c2e1",
      data_added: 41_000_000,
      copies: [{ destination: ICLOUD, outcome: "copied" }],
      warnings: [],
      ...extra,
    },
  };
}

let status: MockInstance<typeof backupApi.getBackupStatus>;
let history: MockInstance<typeof backupApi.getBackupHistory>;

beforeEach(() => {
  vi.spyOn(settingsApi, "getSettings").mockResolvedValue(workspace(SAVED_BLOCK));
  vi.spyOn(settingsApi, "getModelCatalogs").mockResolvedValue({ cache_seconds: 1, providers: {} });
  status = vi.spyOn(backupApi, "getBackupStatus").mockResolvedValue(healthy());
  history = vi.spyOn(backupApi, "getBackupHistory").mockResolvedValue([run(2)]);
});

afterEach(() => vi.restoreAllMocks());

function open(search = "?section=backup") {
  return render(
    <MemoryRouter initialEntries={[`/admin${search}`]}>
      <BackupStatusProvider>
        <AdminPage />
      </BackupStatusProvider>
    </MemoryRouter>,
  );
}

const button = (name: string | RegExp) => screen.getByRole("button", { name });

async function openSetUp() {
  vi.mocked(settingsApi.getSettings).mockResolvedValue(workspace());
  status.mockResolvedValue(OFF);
  open();
  await userEvent.click(await screen.findByRole("button", { name: "Set up backups" }));
  return screen.findByRole("heading", { name: "Set up backups" });
}

async function fillSetUp(password = PASSPHRASE) {
  fireEvent.change(screen.getByLabelText("Backup storage folder"), { target: { value: REPO } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  fireEvent.change(screen.getByLabelText("Repeat password"), { target: { value: password } });
  await userEvent.click(screen.getByRole("checkbox"));
}

describe("Backups off and Set up", () => {
  it("explains backups and offers Set up; Cancel returns to Backups off", async () => {
    await openSetUp();
    await userEvent.click(button("Cancel"));
    expect(await screen.findByRole("heading", { name: "Backups are off" })).toBeVisible();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });

  it("holds Create back until the password is long enough, matches and is saved", async () => {
    await openSetUp();
    const create = button("Create and back up now");
    expect(create).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Backup storage folder"), { target: { value: REPO } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "short" } });
    expect(screen.getByText("Use at least 12 characters.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "long-enough-pass" } });
    fireEvent.change(screen.getByLabelText("Repeat password"), { target: { value: "different" } });
    expect(screen.getByText("The two passwords don't match.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Repeat password"), {
      target: { value: "long-enough-pass" },
    });
    expect(screen.queryByText(/match|12 characters/)).not.toBeInTheDocument();
    expect(create).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox"));
    expect(create).toBeEnabled();
  });

  it("shows and hides both password fields together", async () => {
    await openSetUp();
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    await userEvent.click(button(/Show/));
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "text");
    expect(screen.getByLabelText("Repeat password")).toHaveAttribute("type", "text");
    await userEvent.click(button(/Hide/));
    expect(screen.getByLabelText("Repeat password")).toHaveAttribute("type", "password");
  });

  it("offers five intervals, 12 hours by default, with a hint for each side", async () => {
    await openSetUp();
    const group = screen.getByRole("radiogroup", { name: "Back up every" });
    expect(
      within(group)
        .getAllByRole("radio")
        .map((r) => r.textContent),
    ).toEqual(["4 hours", "6 hours", "12 hours", "1 day", "2 days"]);
    expect(within(group).getByRole("radio", { name: "12 hours" })).toBeChecked();
    expect(screen.getByText(/Recommended: at most half a day/)).toBeVisible();
    await userEvent.click(within(group).getByRole("radio", { name: "4 hours" }));
    expect(screen.getByText(/More often means less to lose/)).toBeVisible();
    await userEvent.click(within(group).getByRole("radio", { name: "2 days" }));
    expect(
      screen.getByText("Up to 2 days of work could be lost if this computer fails."),
    ).toBeVisible();
  });

  it("adds, edits and removes destinations, warning when there are none", async () => {
    await openSetUp();
    expect(screen.getByText(/a failed disk loses them too/)).toBeVisible();
    await userEvent.click(button("Add destination"));
    fireEvent.change(screen.getByLabelText("Destination 1 folder"), { target: { value: ICLOUD } });
    expect(screen.getByText("iCloud Drive")).toBeVisible();
    expect(screen.queryByText(/a failed disk loses them too/)).not.toBeInTheDocument();
    await userEvent.click(button("Add destination"));
    await userEvent.click(button("Remove destination 1"));
    expect(screen.getByLabelText("Destination 1 folder")).toHaveValue("");
  });

  it("keeps digits only in Keep, and refuses zero", async () => {
    await openSetUp();
    const days = screen.getByLabelText("days of every backup");
    fireEvent.change(days, { target: { value: "14a" } });
    expect(days).toHaveValue("14");
    fireEvent.change(days, { target: { value: "0" } });
    expect(days).toHaveValue("14");
    fireEvent.change(days, { target: { value: "" } });
    expect(days).toHaveValue("14");
  });

  it("creates with every answer, then shows the first backup running", async () => {
    const setUp = vi.spyOn(backupApi, "setUpBackup").mockResolvedValue({
      kind: "started",
      status: OFF,
    });
    await openSetUp();
    await fillSetUp();
    await userEvent.click(
      within(screen.getByRole("radiogroup")).getByRole("radio", { name: "1 day" }),
    );
    await userEvent.click(button("Add destination"));
    fireEvent.change(screen.getByLabelText("Destination 1 folder"), { target: { value: ICLOUD } });
    fireEvent.change(screen.getByLabelText("weeks, latest each week"), { target: { value: "6" } });
    vi.mocked(settingsApi.getSettings).mockResolvedValue({
      ...workspace(SAVED_BLOCK),
      revision: "s2",
    });
    status.mockResolvedValue(
      healthy({
        last_success: null,
        running: { operation: "backup", started_at: iso(0), step: "backing_up" },
      }),
    );
    history.mockResolvedValue([]);
    await userEvent.click(button("Create and back up now"));

    expect(setUp).toHaveBeenCalledWith({
      revision: "s1",
      repository: REPO,
      destinations: [ICLOUD],
      interval_hours: 24,
      retention: { keep_within_days: 7, weekly: 6, monthly: 3 },
      password: PASSPHRASE,
    });
    expect(await screen.findByRole("heading", { name: "Making the first backup" })).toBeVisible();
    expect(button("Backing up…")).toBeDisabled();
    expect(screen.getByRole("link", { name: "Status and history" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("shows a refused set-up under the form and keeps the answers", async () => {
    vi.spyOn(backupApi, "setUpBackup").mockResolvedValue({
      kind: "conflict",
      message: "D:/backups/studio holds files. Choose an empty folder.",
      fieldErrors: {},
    });
    await openSetUp();
    await fillSetUp();
    await userEvent.click(button("Create and back up now"));
    expect(await screen.findByRole("alert")).toHaveTextContent("holds files");
    expect(screen.getByLabelText("Backup storage folder")).toHaveValue(REPO);
  });
  it.each([
    [
      { kind: "stale", message: "Something else wrote settings.yaml." },
      "settings.yaml changed on disk. Nothing was overwritten. Reload, then try again.",
    ],
    [
      {
        kind: "conflict",
        message: "Backups are set up; edit the revision in Setup.",
        fieldErrors: {},
      },
      "Backups are set up; edit the revision in Setup.",
    ],
  ] as const)("words a %o set-up refusal by its kind, not its text", async (outcome, shown) => {
    vi.spyOn(backupApi, "setUpBackup").mockResolvedValue(outcome);
    await openSetUp();
    await fillSetUp();
    await userEvent.click(button("Create and back up now"));
    expect(await screen.findByRole("alert")).toHaveTextContent(shown);
  });
});

describe("Setup", () => {
  it("shows the folder and password read-only, and saves only what changed", async () => {
    const save = vi.spyOn(settingsApi, "saveSettings").mockResolvedValue({
      kind: "saved",
      settings: { ...workspace(SAVED_BLOCK), revision: "s2" },
    });
    open("?section=backup&page=setup");
    expect(await screen.findByRole("heading", { name: "Backup settings" })).toBeVisible();
    expect(screen.getByText(REPO)).toBeVisible();
    const form = screen.getByRole("region", { name: "Backup settings" });
    expect(within(form).getByText(/can't be changed here/)).toBeVisible();
    expect(screen.getByText("Set, in .env")).toBeVisible();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(button("Save")).toBeDisabled();
    expect(button("Discard changes")).toBeDisabled();

    await userEvent.click(screen.getByRole("radio", { name: "6 hours" }));
    expect(button("Save")).toBeEnabled();
    await userEvent.click(button("Save"));

    expect(save).toHaveBeenCalledWith("s1", { backup_interval_hours: 6 });
    expect(await screen.findByText("Saved to settings.yaml · every 6 hours")).toBeVisible();
    expect(button("Save")).toBeDisabled();
    expect(screen.getByRole("heading", { name: "Backup settings" })).toBeVisible();
  });

  it("discards changes back to what settings.yaml holds", async () => {
    open("?section=backup&page=setup");
    await screen.findByRole("heading", { name: "Backup settings" });
    await userEvent.click(button("Remove destination 1"));
    expect(screen.queryByLabelText("Destination 1 folder")).not.toBeInTheDocument();
    await userEvent.click(button("Discard changes"));
    expect(screen.getByLabelText("Destination 1 folder")).toHaveValue(ICLOUD);
    expect(button("Save")).toBeDisabled();
  });

  it("shows a refused save with its reason", async () => {
    vi.spyOn(settingsApi, "saveSettings").mockResolvedValue({
      kind: "invalid",
      message: "Refused",
      fieldErrors: { "backup.destinations": "The folder above it does not exist." },
    });
    open("?section=backup&page=setup");
    await screen.findByRole("heading", { name: "Backup settings" });
    fireEvent.change(screen.getByLabelText("Destination 1 folder"), {
      target: { value: "Q:/nowhere/copy" },
    });
    await userEvent.click(button("Save"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The folder above it does not exist.",
    );
  });
});

describe("Status and history", () => {
  it("says when it last backed up, what is next, and lists every run", async () => {
    history.mockResolvedValue([
      run(2),
      {
        ...run(14, {
          outcome: "failed",
          snapshot_id: null,
          data_added: null,
          copies: [],
          message: "Wrong repository password.",
        }),
        kept_as: null,
      },
    ]);
    open();
    expect(await screen.findByRole("heading", { name: "Backed up 2 hrs ago" })).toBeVisible();
    expect(
      screen.getByText("Next backup in about 10 hours · every 12 hours · 5 backups kept"),
    ).toBeVisible();
    const rows = within(await screen.findByRole("table")).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveTextContent("Backed up");
    expect(rows[1]).toHaveTextContent("Copied to iCloud Drive");
    expect(rows[1]).toHaveTextContent("41 MB");
    expect(rows[1]).toHaveTextContent("Recent");
    expect(rows[2]).toHaveTextContent("Failed");
    expect(rows[2]).toHaveTextContent("Wrong repository password.");
    expect(rows[2]).toHaveTextContent("Nothing saved");
    expect(screen.getByText(/Every backup from the last 7 days/)).toBeVisible();
  });

  it("starts a backup with Back up now, and says what the run is doing", async () => {
    const start = vi.spyOn(backupApi, "runBackup").mockResolvedValue(healthy());
    open();
    await screen.findByRole("heading", { name: "Backed up 2 hrs ago" });
    status.mockResolvedValue(
      healthy({
        running: {
          operation: "backup",
          started_at: iso(0),
          step: "waiting",
          waiting_for: "the deploy of now-or-never",
        },
      }),
    );
    await userEvent.click(button("Back up now"));
    expect(start).toHaveBeenCalled();
    expect(
      await screen.findByText("Waiting for the deploy of now-or-never to finish…"),
    ).toBeVisible();
    expect(button("Backing up…")).toBeDisabled();
  });

  it.each([
    [
      { step: "backing_up", files_done: 1206, files_total: 5142 },
      "Backing up… 1,206 of 5,142 files checked",
    ],
    [{ step: "copying", destination: ICLOUD }, "Copying new files to iCloud Drive…"],
  ])("words the running line for %o", async (running, line) => {
    status.mockResolvedValue(
      healthy({ running: { operation: "backup", started_at: iso(0), ...running } }),
    );
    open();
    expect(await screen.findByText(line)).toBeVisible();
  });

  it("highlights the run that finished while the page was open", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      status.mockResolvedValue(
        healthy({ running: { operation: "backup", started_at: iso(0), step: "backing_up" } }),
      );
      const { container } = open();
      await screen.findByRole("table");
      status.mockResolvedValue(healthy({ last_success: iso(0) }));
      history.mockResolvedValue([run(0), run(2)]);
      await act(() => vi.advanceTimersByTimeAsync(2000));
      await waitFor(() => expect(container.querySelectorAll(".bk-run--fresh")).toHaveLength(1));
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("Warnings on the Backup page", () => {
  it("shows a failure with Try again, an amber status and a pill on the destination", async () => {
    const start = vi.spyOn(backupApi, "runBackup").mockResolvedValue(healthy());
    status.mockResolvedValue(
      healthy({
        destinations: [
          {
            path: ICLOUD,
            last_copy: iso(-50),
            problem: "Folder not found.",
            behind: true,
            changed: [],
            unexpected: [],
          },
        ],
        warnings: [
          {
            kind: "behind",
            destination: ICLOUD,
            message: `${ICLOUD} is more than a day behind the backups. Folder not found.`,
            banner: true,
          },
        ],
      }),
    );
    const { container } = open();
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("more than a day behind");
    expect(
      screen.getByRole("heading", { name: "Backed up 2 hrs ago, not copied to iCloud Drive" }),
    ).toBeVisible();
    expect(container.querySelector(".bk-status--warn")).not.toBeNull();
    expect(screen.getByText("Folder not found")).toHaveClass("bk-pill--warn");

    status.mockResolvedValue(healthy());
    await userEvent.click(within(banner).getByRole("button", { name: "Try again" }));
    expect(start).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("names a missing repository, and the storage folder as not found", async () => {
    status.mockResolvedValue(backupsMissing());
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("Backup repository not found");
    expect(screen.getByText("Not found")).toHaveClass("bk-pill--bad");
  });
});

describe("Changed and unexpected files", () => {
  const changed = () =>
    healthy({
      destinations: [
        {
          path: ICLOUD,
          last_copy: iso(-14),
          behind: false,
          changed: [
            { name: "data/7c/7c41e0d2", expected_size: 16_800_000, actual_size: 16_100_000 },
          ],
          unexpected: ["index/a3f9c2e1 2"],
        },
      ],
      warnings: [
        {
          kind: "changed",
          destination: ICLOUD,
          message: `Something else changed files in ${ICLOUD}.`,
          banner: true,
        },
      ],
    });

  it("lists each file with its pill, and stops the copy in the headline", async () => {
    status.mockResolvedValue(changed());
    open();
    const banner = await screen.findByRole("alert");
    const files = within(banner).getAllByRole("listitem");
    expect(files[0]).toHaveTextContent("data/7c/7c41e0d2Changed16.8 MB when copied, 16.1 MB now");
    expect(files[1]).toHaveTextContent("index/a3f9c2e1 2Unexpected");
    expect(
      screen.getByRole("heading", { name: "Backed up 2 hrs ago, iCloud Drive copy stopped" }),
    ).toBeVisible();
    expect(screen.getByText("2 files to check")).toBeVisible();
  });

  it("Cancel in the repair dialog changes nothing", async () => {
    const repair = vi.spyOn(backupApi, "repairDestination");
    status.mockResolvedValue(changed());
    open();
    await userEvent.click(
      await screen.findByRole("button", { name: "Repair the iCloud Drive copy…" }),
    );
    expect(screen.getByRole("dialog", { name: "Repair the iCloud Drive copy" })).toBeVisible();
    await userEvent.click(button("Cancel"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(repair).not.toHaveBeenCalled();
  });

  it("repairs with the buttons held, then names the set-aside folder in a note", async () => {
    let finish!: (result: backupApi.RepairResult) => void;
    const repair = vi
      .spyOn(backupApi, "repairDestination")
      .mockImplementation(() => new Promise((resolve) => (finish = resolve)));
    status.mockResolvedValue(changed());
    open();
    await userEvent.click(
      await screen.findByRole("button", { name: "Repair the iCloud Drive copy…" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("studio-backups-set-aside-");
    await userEvent.click(within(dialog).getByRole("button", { name: "Set aside and copy again" }));
    expect(repair).toHaveBeenCalledWith(ICLOUD);
    expect(within(dialog).getByText("Setting files aside and copying…")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();

    status.mockResolvedValue(healthy());
    await act(async () =>
      finish({
        set_aside: `${ICLOUD}-set-aside-2026-11-23`,
        moved: ["data/7c/7c41e0d2", "index/a3f9c2e1 2"],
        outcome: "copied",
      }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const note = await screen.findByText(
      "Repaired the iCloud Drive copy. 2 files were set aside in studio-backups-set-aside-2026-11-23, next to it.",
    );
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    await userEvent.click(button("Dismiss"));
    expect(note).not.toBeInTheDocument();
  });

  it("keeps the dialog open with the reason when the repair fails", async () => {
    vi.spyOn(backupApi, "repairDestination").mockRejectedValue(
      new Error("iCloud Drive is offline"),
    );
    status.mockResolvedValue(changed());
    open();
    await userEvent.click(
      await screen.findByRole("button", { name: "Repair the iCloud Drive copy…" }),
    );
    await userEvent.click(button("Set aside and copy again"));
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("iCloud Drive is offline");
    expect(within(dialog).getByRole("button", { name: "Set aside and copy again" })).toBeEnabled();
  });
});

describe("Restore", () => {
  const NEWEST = "b".repeat(64);
  const OLDER = `a3f9c2e1${"0".repeat(56)}`;
  const LIVE = "C:/Users/me/studio";
  const restoring = (extra: Partial<backupApi.RestoreStatus> = {}): backupApi.RestoreStatus => ({
    snapshot_id: NEWEST,
    snapshot_time: iso(-2),
    target: `${LIVE}-restore-bbbbbbbb`,
    started_at: iso(0),
    outcome: "running",
    percent: 0.25,
    bytes_done: 5_000_000_000,
    bytes_total: 20_100_000_000,
    files_done: 1285,
    files_total: 5142,
    seconds_left: 600,
    ...extra,
  });
  let start: MockInstance<typeof backupApi.startRestore>;

  beforeEach(() => {
    vi.spyOn(backupApi, "getBackupSnapshots").mockResolvedValue({
      workspace: LIVE,
      snapshots: [
        { id: NEWEST, short_id: "bbbbbbbb", time: iso(-2), files: 5142, size: 20_100_000_000 },
        { id: OLDER, short_id: "a3f9c2e1", time: iso(-26), files: 5100, size: 20_000_000_000 },
      ],
    });
    history.mockResolvedValue([run(2, { snapshot_id: NEWEST }), run(26, { snapshot_id: OLDER })]);
    start = vi.spyOn(backupApi, "startRestore").mockImplementation(async () => {
      status.mockResolvedValue(healthy({ restore: restoring() }));
      return { status: healthy({ restore: restoring() }) };
    });
  });

  async function withPolls(body: () => Promise<void>) {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      await body();
    } finally {
      vi.useRealTimers();
    }
  }
  const poll = () => act(() => vi.advanceTimersByTimeAsync(2000));
  const target = () => screen.getByLabelText<HTMLInputElement>("Restore into");

  async function restoreNewest() {
    open();
    await userEvent.click(await screen.findByRole("button", { name: "Restore…" }));
    await waitFor(() => expect(target().value).toBe(`${LIVE}-restore-bbbbbbbb`));
    await userEvent.click(button("Restore to this folder"));
    return screen.findByRole("dialog", { name: /Restoring the backup from/ });
  }

  it("opens on the newest backup, or a row's, and names the folder after it", async () => {
    open();
    await userEvent.click(await screen.findByRole("button", { name: "Restore…" }));
    await waitFor(() => expect(target().value).toBe(`${LIVE}-restore-bbbbbbbb`));
    expect(screen.getByText("20.1 GB · 5,142 files")).toBeVisible();
    await userEvent.click(button("Cancel"));

    const rows = screen.getAllByRole("row");
    await userEvent.click(within(rows[2] as HTMLElement).getByRole("button", { name: "Restore…" }));
    await waitFor(() => expect(target().value).toBe(`${LIVE}-restore-a3f9c2e1`));
    fireEvent.change(screen.getByLabelText("Backup to restore"), { target: { value: NEWEST } });
    expect(target().value).toBe(`${LIVE}-restore-bbbbbbbb`);
  });

  it("refuses the live workspace at once, and shows the server's refusal in the same place", async () => {
    start.mockResolvedValue({ refused: "D:/full already holds files." });
    open();
    await userEvent.click(await screen.findByRole("button", { name: "Restore…" }));
    await waitFor(() => expect(target().value).not.toBe(""));
    fireEvent.change(target(), { target: { value: `${LIVE}/` } });
    expect(
      screen.getByText("That's your live workspace. Choose a new, empty folder."),
    ).toBeVisible();
    expect(button("Restore to this folder")).toBeDisabled();

    fireEvent.change(target(), { target: { value: "D:/full" } });
    await userEvent.click(button("Restore to this folder"));
    expect(await screen.findByText("D:/full already holds files.")).toBeVisible();
    expect(start).toHaveBeenCalledWith(NEWEST, "D:/full");
  });

  it("shows progress, closes to a strip with Keep working, and Show reopens it", async () => {
    const dialog = await restoreNewest();
    expect(within(dialog).getByText("25%")).toBeVisible();
    expect(within(dialog).getByText("about 10 min left")).toBeVisible();
    expect(within(dialog).getByText("5 of 20.1 GB · 1,285 of 5,142 files")).toBeVisible();

    await userEvent.click(within(dialog).getByRole("button", { name: "Keep working" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText(/25% · 5 of 20.1 GB · about 10 min left/)).toBeVisible();
    for (const restore of screen.getAllByRole("button", { name: "Restore…" }))
      expect(restore).toBeDisabled();
    await userEvent.click(button("Show"));
    expect(screen.getByRole("dialog", { name: /Restoring the backup from/ })).toBeVisible();
  });

  it("finishing with the dialog open shows Restored", () =>
    withPolls(async () => {
      await restoreNewest();
      status.mockResolvedValue(
        healthy({ restore: restoring({ outcome: "succeeded", percent: 1, files_done: 5142 }) }),
      );
      await poll();
      const done = await screen.findByRole("dialog", { name: "Restored 5,142 files" });
      expect(within(done).getByLabelText("Restored folder")).toHaveValue(
        `${LIVE}-restore-bbbbbbbb`,
      );
      await userEvent.click(within(done).getByRole("button", { name: "Done" }));
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(screen.queryByText(/Restored the backup from/)).not.toBeInTheDocument();
    }));

  it("keeps the restore form usable when the request cannot reach the server", async () => {
    start.mockRejectedValueOnce(new Error("Network unavailable"));
    open();
    await userEvent.click(await screen.findByRole("button", { name: "Restore…" }));
    const submit = await screen.findByRole("button", { name: "Restore to this folder" });

    await userEvent.click(submit);

    expect(await screen.findByText("Network unavailable")).toBeVisible();
    expect(submit).toBeEnabled();
  });

  it("finishing with the dialog closed leaves a note whose Show opens Restored", () =>
    withPolls(async () => {
      const dialog = await restoreNewest();
      await userEvent.click(within(dialog).getByRole("button", { name: "Keep working" }));
      status.mockResolvedValue(
        healthy({ restore: restoring({ outcome: "succeeded", percent: 1, files_done: 5142 }) }),
      );
      await poll();
      expect(await screen.findByText(/^Restored the backup from/)).toBeVisible();
      await userEvent.click(button("Show"));
      expect(screen.getByRole("dialog", { name: "Restored 5,142 files" })).toBeVisible();
    }));

  it("Stop restore stops it and says how far it got", async () => {
    const stop = vi.spyOn(backupApi, "stopRestore").mockImplementation(async () => {
      status.mockResolvedValue(healthy({ restore: restoring({ outcome: "stopped" }) }));
      return healthy({ restore: restoring({ outcome: "stopped" }) });
    });
    const dialog = await restoreNewest();
    await userEvent.click(within(dialog).getByRole("button", { name: "Stop restore" }));
    expect(stop).toHaveBeenCalled();
    expect(
      await screen.findByText(
        "Restore stopped at 25%. The folder holds the files restored so far; delete it before restoring there again.",
      ),
    ).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await userEvent.click(button("Dismiss"));
    expect(screen.queryByText(/Restore stopped/)).not.toBeInTheDocument();
  });

  it("a restore that fails says how far it got and why", async () => {
    status.mockResolvedValue(
      healthy({
        restore: restoring({ outcome: "failed", message: "restic: disk full" }),
      }),
    );
    open();
    expect(
      await screen.findByText(
        "The restore failed at 25%: restic: disk full The folder holds the files restored so far; delete it before restoring there again.",
      ),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Show" })).not.toBeInTheDocument();
  });

  it("Copy path in the Restored dialog copies the folder", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    status.mockResolvedValue(
      healthy({ restore: restoring({ outcome: "succeeded", percent: 1, files_done: 5142 }) }),
    );
    open();
    await userEvent.click(await screen.findByRole("button", { name: "Show" }));
    await userEvent.click(button(/Copy path/));
    expect(writeText).toHaveBeenCalledWith(`${LIVE}-restore-bbbbbbbb`);
  });
});
