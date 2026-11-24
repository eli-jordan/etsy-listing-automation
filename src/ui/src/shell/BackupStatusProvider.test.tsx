import { act, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as backupApi from "../api/backup";
import type { BackupStatus } from "../api/backup";
import { backupsOn, backupWarning } from "../test/backup";
import { deferred } from "../test/helpers";
import { type BackupStatusSource, useBackupStatus } from "./backupStatus";
import { BackupStatusProvider } from "./BackupStatusProvider";

/* refresh() is what an action awaits before it reads the status again
   (useRestore's start, Set up's create): it must answer with the status the
   page now draws, never one a newer read has replaced. */

const probe: { source?: BackupStatusSource } = {};
const source = () => probe.source as BackupStatusSource;
const drawn = () => {
  const { view } = source();
  return view.state === "on" ? view.status : null;
};
function Probe() {
  const read = useBackupStatus();
  useEffect(() => {
    probe.source = read;
  });
  return <p>{read.view.state}</p>;
}

afterEach(() => vi.restoreAllMocks());

const OLD = backupsOn({ warnings: [backupWarning("stale")] });
const NEW = backupsOn();

async function mounted(first: Promise<BackupStatus>) {
  const read = vi.spyOn(backupApi, "getBackupStatus").mockReturnValueOnce(first);
  render(
    <BackupStatusProvider>
      <Probe />
    </BackupStatusProvider>,
  );
  return read;
}

describe("refresh", () => {
  it("answers with the newer status when a later read answered first", async () => {
    const slow = deferred<BackupStatus>();
    const read = await mounted(Promise.resolve(OLD));
    await screen.findByText("on");
    read.mockReturnValueOnce(slow.promise).mockResolvedValueOnce(NEW);

    const superseded = source().refresh();
    await act(() => source().refresh());
    expect(drawn()).toBe(NEW);

    await act(async () => slow.resolve(OLD));
    await expect(superseded).resolves.toBe(NEW);
    expect(drawn()).toBe(NEW);
  });

  it("answers with the status it keeps when the read fails", async () => {
    const read = await mounted(Promise.resolve(OLD));
    await screen.findByText("on");
    read.mockRejectedValueOnce(new Error("offline"));
    await expect(act(() => source().refresh())).resolves.toBe(OLD);
    expect(source().view.state).toBe("on");
  });
});
