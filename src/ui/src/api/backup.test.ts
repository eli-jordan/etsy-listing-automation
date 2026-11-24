import { afterEach, describe, expect, it, vi } from "vitest";
import { connectRepository, createRepository, setUpBackup, startRestore } from "./backup";
import { api } from "./client";

/* The backup writes through the typed client's `api` seam. Each answers
   `started` or one refusal vocabulary (`api/refusal.ts`), read from the
   body's `kind`: the status code alone decides nothing. */

const ANSWERS = {
  revision: "s1",
  repository: "D:/backups",
  destinations: [],
  interval_hours: 12 as const,
  password: "a-long-enough-passphrase",
};
const NEW = { revision: "s1", repository: "D:/backups", password: null };

function answer(status: number, error: unknown) {
  vi.spyOn(api, "POST").mockResolvedValue({
    data: undefined,
    error,
    response: new Response(null, { status }),
  } as never);
}

afterEach(() => vi.restoreAllMocks());

describe("set-up, create and connect", () => {
  const writes = [
    () => setUpBackup(ANSWERS),
    () => createRepository(NEW),
    () => connectRepository({ ...NEW, source: "E:/copy" }),
  ];

  it.each([
    [
      "stale (412)",
      412,
      { kind: "stale", message: "changed" },
      { kind: "stale", message: "changed" },
    ],
    [
      "conflict (409)",
      409,
      { kind: "conflict", message: "Holds files.", field_errors: {} },
      { kind: "refused", message: "Holds files.", fieldErrors: {} },
    ],
    [
      "invalid (422)",
      422,
      { kind: "invalid", message: "Refused", field_errors: { password: "Too short" } },
      { kind: "refused", message: "Refused", fieldErrors: { password: "Too short" } },
    ],
  ])("read a %s refusal by its kind", async (_name, status, body, outcome) => {
    answer(status, body);
    for (const write of writes) expect(await write()).toEqual(outcome);
  });

  it("carry the destination a refused Create names to connect instead", async () => {
    answer(409, { kind: "conflict", message: "Holds a copy.", connect_from: "E:/copy" });
    expect(await createRepository(NEW)).toEqual({
      kind: "refused",
      message: "Holds a copy.",
      fieldErrors: {},
      connectFrom: "E:/copy",
    });
  });

  it("throw on an answer that is no refusal", async () => {
    answer(500, { detail: "boom" });
    await expect(setUpBackup(ANSWERS)).rejects.toThrow("boom");
  });
});

describe("startRestore", () => {
  it("reads the domain's refused target as a refusal", async () => {
    answer(409, { detail: "That's your live workspace. Choose a new, empty folder." });
    expect(await startRestore("latest", "C:/live")).toEqual({
      kind: "refused",
      message: "That's your live workspace. Choose a new, empty folder.",
      fieldErrors: {},
    });
  });
});
