import { afterEach, describe, expect, it, vi } from "vitest";
import { setUpBackup } from "./backup";
import { api } from "./client";

/* `POST /api/backup/setup` through the typed client's `api` seam. Both
   stale revisions and folders holding files are `kind: "conflict"`; only
   the HTTP status tells them apart. */

const ANSWERS = {
  revision: "s1",
  repository: "D:/backups",
  destinations: [],
  interval_hours: 12 as const,
  password: "a-long-enough-passphrase",
};

function refuse(status: number, kind: "conflict" | "invalid", message: string) {
  vi.spyOn(api, "POST").mockResolvedValue({
    data: undefined,
    error: { kind, message, field_errors: {} },
    response: new Response(null, { status }),
  } as never);
}

afterEach(() => vi.restoreAllMocks());

describe("setUpBackup", () => {
  it("reports a stale revision (412) as stale, whatever its message", async () => {
    refuse(412, "conflict", "Something else wrote the file.");
    expect(await setUpBackup(ANSWERS)).toEqual({
      kind: "stale",
      message: "Something else wrote the file.",
    });
  });

  it("reports another conflict (409) with its message", async () => {
    refuse(409, "conflict", "The settings revision holds files.");
    expect(await setUpBackup(ANSWERS)).toEqual({
      kind: "conflict",
      message: "The settings revision holds files.",
      fieldErrors: {},
    });
  });

  it("reports a refused answer (422) with its fields", async () => {
    vi.spyOn(api, "POST").mockResolvedValue({
      data: undefined,
      error: { kind: "invalid", message: "Refused", field_errors: { password: "Too short" } },
      response: new Response(null, { status: 422 }),
    } as never);
    expect(await setUpBackup(ANSWERS)).toEqual({
      kind: "invalid",
      message: "Refused",
      fieldErrors: { password: "Too short" },
    });
  });
});
