import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, type MockInstance, vi } from "vitest";
import * as backupApi from "../../../api/backup";
import type { BackupStatus } from "../../../api/backup";
import * as settingsApi from "../../../api/workspaceSettings";
import { BackupStatusProvider } from "../../../shell/BackupStatusProvider";
import { AdminPage } from "../AdminPage";

/* Workspace-backup plan, PR 8: the missing-repository banner's Create a new
   repository and Connect an existing repository (spec, *Missing
   repository*; interactions, *Warnings*), against a mocked HTTP surface. */

const REPO = "D:/backups/studio";
const CLOUD = "C:/Users/me/iCloudDrive/studio-backups";
const PASSPHRASE = ["correct", "horse", "battery"].join("-");
const weights = { reviews: 100 };

function missing(passwordStored: boolean): BackupStatus {
  return {
    enabled: true,
    interval_hours: 12,
    repository: { path: REPO, missing: true, snapshots: 0, password_stored: passwordStored },
    destinations: [],
    warnings: [
      {
        kind: "repository_missing",
        message: `Backup repository not found at ${REPO}. Backups have stopped.`,
        banner: true,
      },
    ],
  };
}

const HEALTHY: BackupStatus = {
  ...missing(true),
  repository: { path: REPO, missing: false, snapshots: 3, password_stored: true },
  warnings: [],
};

let status: MockInstance<typeof backupApi.getBackupStatus>;

beforeEach(() => {
  vi.spyOn(settingsApi, "getSettings").mockResolvedValue({
    revision: "s1",
    template_positions: { scale: { min: 0.8, max: 1.1 }, offset: 0.1, rotation: 15 },
    concurrency: 1,
    providers: [{ name: "codex", enabled: true }],
    weights,
    default_weights: weights,
    step_limit_minutes: 5,
    run_limit_minutes: 20,
    backup: { repository: REPO, destinations: [], interval_hours: 12 },
  });
  vi.spyOn(settingsApi, "getModelCatalogs").mockResolvedValue({ cache_seconds: 1, providers: {} });
  status = vi.spyOn(backupApi, "getBackupStatus").mockResolvedValue(missing(true));
  vi.spyOn(backupApi, "getBackupHistory").mockResolvedValue([]);
});

afterEach(() => vi.restoreAllMocks());

async function openMissing(passwordStored = true) {
  status.mockResolvedValue(missing(passwordStored));
  render(
    <MemoryRouter initialEntries={["/admin?section=backup"]}>
      <BackupStatusProvider>
        <AdminPage />
      </BackupStatusProvider>
    </MemoryRouter>,
  );
  return screen.findByText(/Backup repository not found/);
}

const button = (name: string | RegExp) => screen.getByRole("button", { name });
const dialog = () => screen.getByRole("dialog");
const type = (label: string, value: string) =>
  fireEvent.change(within(dialog()).getByLabelText(label), { target: { value } });

describe("Create a new repository", () => {
  it("creates in the confirmed folder with the stored password, then closes", async () => {
    const create = vi
      .spyOn(backupApi, "createRepository")
      .mockResolvedValue({ kind: "started", status: HEALTHY });
    await openMissing();
    await userEvent.click(button("Create a new repository"));

    expect(within(dialog()).getByLabelText("New backup storage folder")).toHaveValue(REPO);
    expect(within(dialog()).queryByLabelText("Password")).not.toBeInTheDocument();
    type("New backup storage folder", "E:/backups");
    status.mockResolvedValue(HEALTHY);
    await userEvent.click(button("Create and back up now"));

    expect(create).toHaveBeenCalledWith({
      revision: "s1",
      repository: "E:/backups",
      password: null,
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.queryByText(/not found/)).not.toBeInTheDocument());
  });

  it("asks for a password of 12 characters, twice, when none is stored", async () => {
    const create = vi
      .spyOn(backupApi, "createRepository")
      .mockResolvedValue({ kind: "started", status: HEALTHY });
    await openMissing(false);
    await userEvent.click(button("Create a new repository"));
    const submit = button("Create and back up now");

    type("Password", "short");
    type("Repeat password", "short");
    expect(submit).toBeDisabled();
    type("Password", PASSPHRASE);
    expect(submit).toBeDisabled();
    type("Repeat password", PASSPHRASE);
    expect(submit).toBeDisabled();
    await userEvent.click(within(dialog()).getByRole("checkbox"));
    await userEvent.click(submit);

    expect(create).toHaveBeenCalledWith({ revision: "s1", repository: REPO, password: PASSPHRASE });
  });

  it("shows a refusal in the dialog, keeps the answers, and Cancel changes nothing", async () => {
    vi.spyOn(backupApi, "createRepository").mockResolvedValue({
      kind: "conflict",
      message: "E:/pictures already holds files.",
      fieldErrors: {},
    });
    await openMissing();
    await userEvent.click(button("Create a new repository"));
    type("New backup storage folder", "E:/pictures");
    await userEvent.click(button("Create and back up now"));

    expect(await within(dialog()).findByRole("alert")).toHaveTextContent("already holds files");
    expect(within(dialog()).getByLabelText("New backup storage folder")).toHaveValue("E:/pictures");
    await userEvent.click(within(dialog()).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText(/Backup repository not found/)).toBeVisible();
  });
});

describe("Connect an existing repository", () => {
  it("copies the chosen repository here, showing it is working, then closes", async () => {
    let finish: ((outcome: backupApi.SetUpOutcome) => void) | undefined;
    const pending = new Promise<backupApi.SetUpOutcome>((resolve) => {
      finish = resolve;
    });
    const connect = vi.spyOn(backupApi, "connectRepository").mockReturnValue(pending);
    await openMissing(false);
    await userEvent.click(button("Connect an existing repository"));
    const submit = button("Copy and connect");
    expect(submit).toBeDisabled();

    type("Copy from", CLOUD);
    expect(within(dialog()).getByLabelText("Copy into")).toHaveValue(REPO);
    type("Password", "old password");
    await userEvent.click(submit);

    expect(connect).toHaveBeenCalledWith({
      revision: "s1",
      source: CLOUD,
      repository: REPO,
      password: "old password",
    });
    expect(within(dialog()).getByRole("status")).toHaveTextContent("Copying");
    expect(within(dialog()).getByRole("button", { name: "Cancel" })).toBeDisabled();
    status.mockResolvedValue(HEALTHY);
    finish?.({ kind: "started", status: HEALTHY });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("names a wrong password in the dialog and lets the seller try again", async () => {
    const connect = vi.spyOn(backupApi, "connectRepository").mockResolvedValue({
      kind: "invalid",
      message: "That password does not open this repository. Nothing was saved.",
      fieldErrors: {},
    });
    await openMissing(false);
    await userEvent.click(button("Connect an existing repository"));
    type("Copy from", CLOUD);
    type("Password", "typo");
    await userEvent.click(button("Copy and connect"));

    expect(await within(dialog()).findByRole("alert")).toHaveTextContent("does not open");
    expect(button("Copy and connect")).toBeEnabled();
    type("Password", "the right one");
    expect(within(dialog()).queryByRole("alert")).not.toBeInTheDocument();
    expect(connect).toHaveBeenCalledTimes(1);
  });

  it("uses the stored password without asking", async () => {
    const connect = vi
      .spyOn(backupApi, "connectRepository")
      .mockResolvedValue({ kind: "started", status: HEALTHY });
    await openMissing(true);
    await userEvent.click(button("Connect an existing repository"));
    expect(within(dialog()).queryByLabelText("Password")).not.toBeInTheDocument();
    type("Copy from", CLOUD);
    await userEvent.click(button("Copy and connect"));

    expect(connect).toHaveBeenCalledWith(expect.objectContaining({ password: null }));
  });
});
