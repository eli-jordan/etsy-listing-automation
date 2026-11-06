import { describe, expect, it, vi } from "vitest";
import { deferred } from "../test/helpers";
import { listingDetail as detail } from "../test/listings";
import { ManualClock, turns } from "../test/manualClock";
import type { Issue, ListingDetail } from "../types";
import { type AutosaveTransport, ListingAutosave, type SaveOutcome } from "./listingAutosave";
import { AUTOSAVE_DEBOUNCE_MS, WRITTEN } from "./writeLoop";

const written = (fresh: ListingDetail): SaveOutcome => ({ saved: true, detail: fresh });

function refusal(
  field_errors: Record<string, string> = {},
  issues: Issue[] | null = null,
): SaveOutcome {
  return { saved: false, issues, field_errors };
}

const ROOT = "media position 1 is the thumbnail and must be an image";

/** The editor over an in-memory transport. Every call answers what a test
 * gives it, and a save with nothing scripted writes the listing unchanged. */
function editing(
  name: string | null = "take-a-hike",
  initial: ListingDetail = detail(),
  over: Partial<AutosaveTransport> = {},
) {
  const clock = new ManualClock();
  const transport = {
    describe: vi.fn(over.describe ?? (async () => initial)),
    create: vi.fn(over.create ?? (async (next: string) => written(detail({ name: next })))),
    save: vi.fn(over.save ?? (async () => written(detail()))),
    rename: vi.fn(over.rename ?? (async (_from: string, to: string) => detail({ name: to }))),
  };
  const autosave = new ListingAutosave(
    name,
    initial,
    {
      document: (d) => ({ colors: d.colors, brief: d.brief, etsy: d.etsy }),
      ...transport,
      describe: over.describe === null ? null : transport.describe,
    },
    clock,
  );
  const onNamed = vi.fn();
  autosave.connect(onNamed);
  return {
    autosave,
    transport,
    onNamed,
    view: () => autosave.snapshot(),
    settle: async () => {
      clock.advance(AUTOSAVE_DEBOUNCE_MS);
      await turns();
    },
  };
}

const draft = () =>
  detail({ name: "", garment_profile: "", design: {}, colors: [], prices: {}, media: [] });

describe("what the editor shows", () => {
  it("starts with listing.yaml's actual modification time", () => {
    const modifiedAt = "2026-09-16T08:30:00Z";
    const { view } = editing("take-a-hike", detail({ modified_at: modifiedAt }));

    expect(view().save).toEqual({ kind: "saved", savedAt: Date.parse(modifiedAt) });
  });

  it("starts an unnamed draft as unnamed", () => {
    expect(editing(null, draft()).view().save).toEqual({ kind: "unnamed" });
  });

  it("shows an edit at once, before the save goes", () => {
    const { autosave, view, transport } = editing();

    autosave.update({ colors: ["black", "white"] });

    expect(view().detail.colors).toEqual(["black", "white"]);
    expect(transport.save).not.toHaveBeenCalled();
  });

  it("tells subscribers when it changes", () => {
    const { autosave } = editing();
    const listener = vi.fn();
    const unsubscribe = autosave.subscribe(listener);

    autosave.update({ colors: ["white"] });
    unsubscribe();
    autosave.update({ colors: ["black"] });

    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("shows a bare design ref the way the server stores it, and sends it bare", async () => {
    const { autosave, view, transport, settle } = editing();

    // The form `listing.yaml` may still hold. Held as a string, `Object.keys`
    // on it reports one "artwork" per character.
    autosave.update({ design: "designs/take-a-hike.png" });
    expect(view().detail.design).toEqual({ default: "designs/take-a-hike.png" });

    await settle();
    expect(transport.save.mock.calls[0]?.[1]).toEqual({ design: "designs/take-a-hike.png" });
  });
});

describe("saving a listing on disk", () => {
  it("sends the delta and the whole document", async () => {
    const { autosave, transport, settle } = editing();

    autosave.update({ colors: ["white"] });
    await settle();

    const [name, patch, candidate] = transport.save.mock.calls[0] ?? [];
    expect(name).toBe("take-a-hike");
    expect(patch).toEqual({ colors: ["white"] });
    expect(candidate).toMatchObject({ colors: ["white"], brief: detail().brief });
  });

  it("merges edits to different etsy sub-fields into one nested object", async () => {
    const { autosave, transport, settle } = editing();

    autosave.update({ etsy: { title: "New Title" } });
    autosave.update({ etsy: { section: "Apparel" } });
    await settle();

    expect(transport.save.mock.calls[0]?.[1]).toEqual({
      etsy: { title: "New Title", section: "Apparel" },
    });
  });

  it("replaces what it shows with the server's response once it lands", async () => {
    const server = detail({ colors: ["white"], issues: [] });
    const { autosave, view, settle } = editing("take-a-hike", detail(), {
      save: async () => written(server),
    });

    autosave.update({ colors: ["white"] });
    await settle();

    expect(view().detail).toBe(server);
    expect(view().save.kind).toBe("saved");
  });

  it("keeps an edit made during a save on screen over that save's response", async () => {
    const answer = deferred<SaveOutcome>();
    const { autosave, view, settle } = editing("take-a-hike", detail(), {
      save: () => answer.promise,
    });

    autosave.update({ brief: "A trail" });
    await settle();
    autosave.update({ brief: "A trail shirt." });
    answer.resolve(written(detail({ brief: "A trail" })));
    await turns();

    expect(view().detail.brief).toBe("A trail shirt.");
  });

  it("says saving, not saved, while a newer edit is waiting", async () => {
    const answer = deferred<SaveOutcome>();
    const { autosave, view, settle } = editing("take-a-hike", detail(), {
      save: () => answer.promise,
    });

    autosave.update({ colors: ["white"] });
    await settle();
    expect(view().save.kind).toBe("saving");
    autosave.update({ brief: "x" });
    answer.resolve(written(detail()));
    await turns();

    expect(view().save.kind).toBe("saving");
  });

  it("makes each landed save a new state, so two can be told apart", async () => {
    const { autosave, view, settle } = editing();

    autosave.update({ colors: ["white"] });
    await settle();
    const first = view().save;
    autosave.update({ colors: ["black"] });
    await settle();

    expect(view().save.kind).toBe("saved");
    expect(view().save).not.toBe(first);
  });

  it("says the save failed, keeping the edit on screen", async () => {
    const { autosave, view, settle } = editing("take-a-hike", detail(), {
      save: () => Promise.reject(new Error("500")),
    });

    autosave.update({ colors: ["white"] });
    await settle();

    expect(view().save).toEqual({ kind: "save-failed" });
    expect(view().detail.colors).toEqual(["white"]);
  });

  it("answers a flush that wrote everything", async () => {
    const { autosave } = editing();

    autosave.update({ colors: ["white"] });

    await expect(autosave.flush()).resolves.toEqual(WRITTEN);
  });

  it("answers a flush with why the save failed", async () => {
    const { autosave } = editing("take-a-hike", detail(), {
      save: () => Promise.reject(new Error("the disk is full")),
    });

    autosave.update({ colors: ["white"] });

    await expect(autosave.flush()).resolves.toEqual({
      written: false,
      message: "the disk is full",
    });
  });
});

describe("a document the server will not write", () => {
  /* A PATCH whose merged document contradicts itself is answered 200 with
     `field_errors` and the listing unchanged. Treating that as saved dropped
     the edit from `pending` while it stayed on screen; the next edit then
     saved on its own, and its response put the unwritten values back to
     what the file still held -- colours and the swatch template snapping
     back with no sign anything had failed. */
  const refuseOnce = (then: ListingDetail) =>
    vi
      .fn<AutosaveTransport["save"]>()
      .mockResolvedValueOnce(refusal({ __root__: ROOT }))
      .mockResolvedValue(written(then));

  it("says it is not saved and why, keeping the values on screen", async () => {
    const { autosave, view, settle } = editing("take-a-hike", detail(), {
      save: refuseOnce(detail()),
    });

    autosave.update({ colors: ["white"] });
    await settle();

    expect(view().save).toEqual({ kind: "unsaved", reason: ROOT });
    expect(view().detail.colors).toEqual(["white"]);
    expect(view().detail.field_errors).toEqual({ __root__: ROOT });
  });

  it("says unsaved with no reason when a field owns the problem", async () => {
    const { autosave, view, settle } = editing("take-a-hike", detail(), {
      save: async () => refusal({ title: "too long" }),
    });

    autosave.update({ colors: ["white"] });
    await settle();

    expect(view().save).toEqual({ kind: "unsaved" });
  });

  it("answers a flush with the refusal's own words", async () => {
    const { autosave } = editing("take-a-hike", detail(), {
      save: async () => refusal({ title: "too long" }),
    });

    autosave.update({ colors: ["white"] });

    await expect(autosave.flush()).resolves.toEqual({ written: false, message: "too long" });
  });

  it("answers a flush for a refusal that names nothing", async () => {
    const { autosave } = editing("take-a-hike", detail(), { save: async () => refusal() });

    autosave.update({ colors: [] });

    await expect(autosave.flush()).resolves.toMatchObject({ written: false });
  });

  it("sends the refused edit again with the next one, and ends up saved", async () => {
    const save = refuseOnce(detail({ colors: ["white"], brief: "x" }));
    const { autosave, view, settle } = editing("take-a-hike", detail(), { save });

    autosave.update({ colors: ["white"] });
    await settle();
    autosave.update({ brief: "x" });
    await settle();

    expect(save.mock.lastCall?.[1]).toEqual({ colors: ["white"], brief: "x" });
    expect(view().detail.colors).toEqual(["white"]);
    expect(view().save.kind).toBe("saved");
  });

  it("shows the refusal's issues where it has them", async () => {
    const issue: Issue = {
      severity: "block",
      tab: "variants",
      where: "Variants › Colours",
      message: "Turn on at least one colour.",
    };
    const { autosave, view, settle } = editing("heavyweight-tee", detail(), {
      save: async () => refusal({}, [issue]),
    });

    autosave.update({ colors: [] });
    await settle();

    expect(view().detail.issues).toEqual([issue]);
    expect(view().detail.colors).toEqual([]);
  });

  it("gives a whole-document transport every held edit on the retry", async () => {
    const save = vi
      .fn<AutosaveTransport["save"]>()
      .mockResolvedValueOnce(refusal())
      .mockResolvedValue(written(detail({ colors: ["ivory"], brief: "x" })));
    const { autosave, settle } = editing("heavyweight-tee", detail(), { save });

    autosave.update({ colors: [] });
    await settle();
    autosave.update({ brief: "x" });
    autosave.update({ colors: ["ivory"] });
    await settle();

    expect(save.mock.lastCall?.[2]).toMatchObject({ colors: ["ivory"], brief: "x" });
  });
});

describe("adopting what the server wrote", () => {
  const BRIEF = "Drafted by the AI run.";

  it("shows the value without saving it again or touching the save state", async () => {
    const { autosave, view, transport, settle } = editing();
    const before = view().save;

    autosave.adopt({ brief: BRIEF });
    await settle();

    expect(view().detail.brief).toBe(BRIEF);
    expect(view().save).toBe(before);
    expect(transport.save).not.toHaveBeenCalled();
  });

  it("leaves an edit that is still pending to be sent as it was", async () => {
    const { autosave, transport, settle } = editing();

    autosave.update({ colors: ["white"] });
    autosave.adopt({ brief: BRIEF });
    await settle();

    expect(transport.save.mock.calls[0]?.[1]).toEqual({ colors: ["white"] });
  });

  it("keeps the value when a save sent before it was written answers without it", async () => {
    // The PATCH reached the server before the AI run wrote the brief, so its
    // response describes a file with no brief -- older than what was adopted.
    const answer = deferred<SaveOutcome>();
    const { autosave, view, settle } = editing("take-a-hike", detail(), {
      save: () => answer.promise,
    });

    autosave.update({ colors: ["white"] });
    await settle();
    autosave.adopt({ brief: BRIEF });
    answer.resolve(written(detail({ colors: ["white"] })));
    await turns();

    expect(view().detail.brief).toBe(BRIEF);
    expect(view().detail.colors).toEqual(["white"]);
    expect(view().save.kind).toBe("saved");
  });

  it("takes the server's word again once a save sent after it answers", async () => {
    const save = vi
      .fn<AutosaveTransport["save"]>()
      .mockResolvedValueOnce(written(detail({ colors: ["white"], brief: BRIEF })))
      .mockResolvedValueOnce(
        written(detail({ colors: ["red"], brief: "Changed in another tab." })),
      );
    const { autosave, view, settle } = editing("take-a-hike", detail(), { save });

    autosave.adopt({ brief: BRIEF });
    autosave.update({ colors: ["white"] });
    await settle();
    autosave.update({ colors: ["red"] });
    await settle();

    expect(view().detail.brief).toBe("Changed in another tab.");
  });

  it("lets the seller's own edit of the field win over the adopted value", async () => {
    const answer = deferred<SaveOutcome>();
    const save = vi
      .fn<AutosaveTransport["save"]>()
      .mockReturnValueOnce(answer.promise)
      .mockResolvedValue(written(detail({ colors: ["white"], brief: "Mine." })));
    const { autosave, view, settle } = editing("take-a-hike", detail(), { save });

    autosave.update({ colors: ["white"] });
    await settle();
    autosave.adopt({ brief: BRIEF });
    autosave.update({ brief: "Mine." });
    answer.resolve(written(detail({ colors: ["white"] })));
    await settle();

    expect(view().detail.brief).toBe("Mine.");
    expect(save.mock.lastCall?.[1]).toEqual({ brief: "Mine." });
  });
});

describe("before the listing exists", () => {
  it("describes the whole document, writing nothing, while unnamed", async () => {
    const { autosave, view, transport, settle } = editing(null, draft());

    autosave.update({ colors: ["black"] });
    await settle();

    // Not the delta: there is nothing on the server to merge one into.
    expect(transport.describe.mock.calls[0]?.[0]).toMatchObject({ colors: ["black"] });
    expect(transport.create).not.toHaveBeenCalled();
    expect(view().save.kind).toBe("unnamed");
  });

  it("keeps an edit on screen over the description of it", async () => {
    const { autosave, view, settle } = editing(null, draft(), {
      describe: async () => draft(),
    });

    autosave.update({ colors: ["black"] });
    await settle();

    expect(view().detail.colors).toEqual(["black"]);
  });

  it("takes the issues a description finds", async () => {
    const issue: Issue = { severity: "block", tab: "details", where: "Title", message: "Add one." };
    const { autosave, view, settle } = editing(null, draft(), {
      describe: async () => ({ ...draft(), issues: [issue] }),
    });

    autosave.update({ colors: ["black"] });
    await settle();

    expect(view().detail.issues).toEqual([issue]);
  });

  it("says nothing when a description fails, and describes again on the next edit", async () => {
    const describeDraft = vi
      .fn<NonNullable<AutosaveTransport["describe"]>>()
      .mockRejectedValueOnce(new Error("500"))
      .mockResolvedValue(draft());
    const { autosave, view, settle } = editing(null, draft(), { describe: describeDraft });

    autosave.update({ colors: ["black"] });
    await settle();
    expect(view().save).toEqual({ kind: "unnamed" });

    autosave.update({ brief: "x" });
    await settle();
    expect(describeDraft.mock.lastCall?.[0]).toMatchObject({ colors: ["black"], brief: "x" });
  });

  it("sends nothing where a transport has no describing", async () => {
    const { autosave } = editing(null, draft(), { describe: null });

    autosave.update({ colors: ["black"] });

    await expect(autosave.flush()).resolves.toMatchObject({ written: false });
  });

  it("answers a flush that the draft is not on disk, with or without edits", async () => {
    const { autosave } = editing(null, draft());

    await expect(autosave.flush()).resolves.toMatchObject({ written: false });
    autosave.update({ colors: ["black"] });
    await expect(autosave.flush()).resolves.toMatchObject({ written: false });
  });

  it("naming it creates it, carrying everything edited beforehand", async () => {
    const { autosave, view, transport, onNamed } = editing(null, draft());
    const named = detail({ name: "my-shirt" });
    transport.create.mockResolvedValue(written(named));

    autosave.update({ colors: ["black"] });
    autosave.commitName("my-shirt");
    await turns();

    expect(transport.create).toHaveBeenCalledTimes(1);
    expect(transport.create.mock.calls[0]?.[0]).toBe("my-shirt");
    expect(transport.create.mock.calls[0]?.[1]).toMatchObject({ colors: ["black"] });
    expect(onNamed).toHaveBeenCalledWith("my-shirt", named);
    expect(view().save.kind).toBe("saved");
  });

  it("names a draft that has no edits", async () => {
    const { autosave, transport } = editing(null, draft());

    autosave.commitName("my-shirt");
    await turns();

    expect(transport.create).toHaveBeenCalledTimes(1);
  });

  it("keeps an edit made while the create was in flight, sending it under the name", async () => {
    /* The window ADR-0003's drafted brief resolves in: a design pick names the
       draft and starts the create, and the brief arrives before the server
       answers. It went missing every time when the create cleared everything
       on success -- the listing appeared, the brief did not, and nothing said
       so. */
    const answer = deferred<SaveOutcome>();
    const { autosave, view, transport, settle } = editing(null, draft(), {
      create: () => answer.promise,
    });

    autosave.update({ colors: ["black"] });
    autosave.commitName("my-shirt");
    autosave.update({ brief: "Drafted from the design." });
    answer.resolve(written(detail({ name: "my-shirt" })));
    await turns();
    expect(view().detail.brief).toBe("Drafted from the design.");
    expect(view().save.kind).toBe("saving");

    await settle();
    expect(transport.save.mock.calls[0]?.[0]).toBe("my-shirt");
    expect(transport.save.mock.calls[0]?.[1]).toEqual({ brief: "Drafted from the design." });
  });

  it("leaves a refused create unsaved, and the next edit retries it by name", async () => {
    const create = vi
      .fn<AutosaveTransport["create"]>()
      .mockResolvedValueOnce(refusal())
      .mockResolvedValueOnce(written(detail({ name: "my-shirt" })));
    const { autosave, view, onNamed, settle } = editing(null, draft(), { create });

    autosave.commitName("my-shirt");
    await turns();
    expect(view().save.kind).toBe("unsaved");
    expect(onNamed).not.toHaveBeenCalled();

    // The edit that supplies what was missing is the retry: the user does not
    // have to type the name again.
    autosave.update({ pricing_plan: "pricing-plans/tee.yaml" });
    await settle();

    expect(create.mock.calls[1]?.[0]).toBe("my-shirt");
    expect(create.mock.calls[1]?.[1]).toMatchObject({ pricing_plan: "pricing-plans/tee.yaml" });
    expect(onNamed).toHaveBeenCalledTimes(1);
  });

  it("reports a taken name without losing the draft", async () => {
    const { autosave, view } = editing(null, draft(), {
      create: () => Promise.reject(new Error("409")),
    });

    autosave.update({ colors: ["black"] });
    autosave.commitName("take-a-hike");
    await turns();

    expect(view().save).toEqual({ kind: "name-taken", name: "take-a-hike" });
    expect(view().detail.colors).toEqual(["black"]);
  });
});

describe("renaming", () => {
  it("writes a pending edit under the old name before the directory moves", async () => {
    const order: string[] = [];
    const { autosave, onNamed } = editing("take-a-hike", detail(), {
      save: async (name) => {
        order.push(`save ${name}`);
        return written(detail());
      },
      rename: async (from, to) => {
        order.push(`rename ${from} ${to}`);
        return detail({ name: to });
      },
    });

    autosave.update({ colors: ["white"] });
    autosave.commitName("hike-away");
    await turns();

    expect(order).toEqual(["save take-a-hike", "rename take-a-hike hike-away"]);
    expect(onNamed).toHaveBeenCalledWith(
      "hike-away",
      expect.objectContaining({ name: "hike-away" }),
    );
  });

  it("waits for a save already out, so the two cannot cross", async () => {
    const answer = deferred<SaveOutcome>();
    const { autosave, transport, settle } = editing("take-a-hike", detail(), {
      save: () => answer.promise,
    });

    autosave.update({ colors: ["white"] });
    await settle();
    autosave.commitName("hike-away");
    await turns();
    expect(transport.rename).not.toHaveBeenCalled();

    answer.resolve(written(detail()));
    await turns();
    expect(transport.rename).toHaveBeenCalledTimes(1);
  });

  it("sends an edit made during it under the new name, keeping it on screen", async () => {
    const answer = deferred<ListingDetail>();
    const { autosave, view, transport, settle } = editing("take-a-hike", detail(), {
      rename: () => answer.promise,
    });

    autosave.commitName("hike-away");
    autosave.update({ colors: ["white"] });
    answer.resolve(detail({ name: "hike-away" }));
    await turns();
    expect(view().detail.colors).toEqual(["white"]);

    await settle();
    expect(transport.save.mock.calls[0]?.[0]).toBe("hike-away");
  });

  it("makes a flush wait for it", async () => {
    const answer = deferred<ListingDetail>();
    const { autosave } = editing("take-a-hike", detail(), { rename: () => answer.promise });
    let flushed = false;

    autosave.commitName("hike-away");
    void autosave.flush().then(() => (flushed = true));
    await turns();
    expect(flushed).toBe(false);

    answer.resolve(detail({ name: "hike-away" }));
    await turns();
    expect(flushed).toBe(true);
  });

  it("leaves the listing where it was when the server refuses the name", async () => {
    const { autosave, view, transport, onNamed, settle } = editing("take-a-hike", detail(), {
      rename: () => Promise.reject(new Error("409")),
    });

    autosave.commitName("taken");
    await turns();

    expect(view().save).toEqual({ kind: "name-taken", name: "taken" });
    expect(onNamed).not.toHaveBeenCalled();

    autosave.update({ colors: ["white"] });
    await settle();
    expect(transport.save.mock.calls[0]?.[0]).toBe("take-a-hike");
  });

  it("does nothing for the name it already has", async () => {
    const { autosave, transport } = editing();

    autosave.commitName("take-a-hike");
    await turns();

    expect(transport.rename).not.toHaveBeenCalled();
  });

  it("ignores a second name while the first is being settled", async () => {
    const answer = deferred<ListingDetail>();
    const rename = vi.fn<AutosaveTransport["rename"]>(() => answer.promise);
    const { autosave } = editing("take-a-hike", detail(), { rename });

    autosave.commitName("hike-away");
    autosave.commitName("hike-further");
    answer.resolve(detail({ name: "hike-away" }));
    await turns();

    expect(rename).toHaveBeenCalledTimes(1);
  });

  it("is stopped by an edit the server refuses, which stays", async () => {
    const save = vi
      .fn<AutosaveTransport["save"]>()
      .mockResolvedValueOnce(refusal({ __root__: ROOT }))
      .mockResolvedValue(written(detail({ colors: ["white"] })));
    const { autosave, view, transport, onNamed } = editing("take-a-hike", detail(), { save });

    autosave.update({ colors: ["white"] });
    autosave.commitName("hike-away");
    await turns();

    expect(transport.rename).not.toHaveBeenCalled();
    expect(onNamed).not.toHaveBeenCalled();
    expect(view().save).toEqual({ kind: "unsaved", reason: ROOT });
    expect(view().detail.colors).toEqual(["white"]);

    await autosave.flush();
    expect(save.mock.lastCall?.[0]).toBe("take-a-hike");
    expect(save.mock.lastCall?.[1]).toEqual({ colors: ["white"] });
  });

  it("is stopped by a save that fails, and says the save failed", async () => {
    const { autosave, view, transport } = editing("take-a-hike", detail(), {
      save: () => Promise.reject(new Error("500")),
    });

    autosave.update({ colors: ["white"] });
    autosave.commitName("hike-away");
    await turns();

    expect(transport.rename).not.toHaveBeenCalled();
    expect(view().save).toEqual({ kind: "save-failed" });
  });

  it("can be tried again once a stopped rename is over", async () => {
    const save = vi
      .fn<AutosaveTransport["save"]>()
      .mockResolvedValueOnce(refusal())
      .mockResolvedValue(written(detail()));
    const { autosave, transport } = editing("take-a-hike", detail(), { save });

    autosave.update({ colors: ["white"] });
    autosave.commitName("hike-away");
    await turns();
    autosave.commitName("hike-away");
    await turns();

    expect(transport.rename).toHaveBeenCalledTimes(1);
  });
});
