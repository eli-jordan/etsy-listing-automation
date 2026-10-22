import { act, renderHook, waitFor } from "@testing-library/react";
import type { Middleware } from "openapi-fetch";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { MaskEdit, MaskOperation, Preparation, PreparationJob } from "../api/preparation";
import { controlledClock } from "../test/clock";
import { deferred, must } from "../test/helpers";
import { MARIGOLD, READY, SINGLE } from "../test/marigold";
import type { TemplateConfigState } from "../types";
import { AUTOSAVE_DEBOUNCE_MS } from "./useAutosave";
import { useTemplateSession } from "./useTemplateSession";

// Node requires absolute Request URLs; browsers resolve the app's relative paths.
vi.hoisted(() => {
  class BrowserRequest extends Request {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(typeof input === "string" ? new URL(input, "http://localhost") : input, init);
    }
  }
  vi.stubGlobal("Request", BrowserRequest);
});

const MODIFIED_AT = "Wed, 17 Sep 2026 18:30:00 GMT";

const PHOTO_WARP: TemplateConfigState = {
  ...SINGLE,
  renderer: {
    type: "photo-warp",
    config: {
      displace: { enabled: false, strength: 0 },
      shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
    },
  },
};

function edited(config: TemplateConfigState, x: number): TemplateConfigState {
  return config.kind === "single"
    ? { ...config, bounding_box: [{ x, y: 0 }, ...config.bounding_box.slice(1)] as never }
    : config;
}

function stroke(x: number): MaskOperation {
  return { type: "stroke", mode: "mask", diameter_px: 12, points: [[x, x]] };
}

function job(over: Partial<PreparationJob> = {}): PreparationJob {
  return {
    id: "job-1",
    template: "tee",
    kind: "prepare",
    phase: "queued",
    step: "queued",
    elapsed: 0,
    placements_completed: 0,
    config_revision: "r1",
    placements_total: 1,
    error: null,
    last_event_sequence: 0,
    queue_position: 1,
    engine_version: null,
    ...over,
  };
}

/** The template endpoints as the server keeps them: a template.yaml per
 * name with a revision that every accepted PUT advances, and `If-Match`
 * checked against it. Requests reach it through the generated client's own
 * middleware, so the session runs its real HTTP functions against real
 * `Response`s. */
class FakeServer {
  disk = new Map<string, { config: TemplateConfigState; revision: string }>();
  preparation: Omit<Preparation, "template"> = { ...READY, config_revision: "r1" };
  /** What each PUT carried, in arrival order. */
  puts: { name: string; ifMatch: string | null; body: Record<string, unknown> }[] = [];
  log: string[] = [];
  jobs: Record<string, unknown>[] = [];
  /** Answers a PUT instead of the default; return undefined to fall through. */
  onPut: ((name: string) => Promise<Response | undefined> | Response | undefined) | null = null;
  private writes = 0;

  middleware: Middleware = {
    onRequest: async ({ request }) => {
      const path = decodeURIComponent(new URL(request.url).pathname);
      const config = /^\/api\/templates\/(.+)\/config$/.exec(path);
      const preparation = /^\/api\/templates\/(.+)\/preparation$/.exec(path);
      this.log.push(`${request.method} ${path}`);
      if (config && request.method === "GET") return this.read(must(config[1]));
      if (config && request.method === "PUT") return this.write(must(config[1]), request);
      if (preparation)
        return Response.json({ ...this.preparation, template: must(preparation[1]) });
      if (request.method === "DELETE" && path === "/api/preparation/jobs/job-1")
        return Response.json(job({ phase: "cancelled" }));
      if (path === "/api/preparation/jobs") {
        const body = (await request.json()) as Record<string, unknown>;
        this.jobs.push(body);
        return Response.json(job({ config_revision: String(body.config_revision) }), {
          status: 202,
        });
      }
      return Response.json({ detail: "unexpected " + path }, { status: 500 });
    },
  };

  private read(name: string): Response {
    const stored = this.disk.get(name);
    if (!stored) return Response.json({ detail: "no template.yaml" }, { status: 404 });
    return Response.json(stored.config, {
      headers: { ETag: `"${stored.revision}"`, "Last-Modified": MODIFIED_AT },
    });
  }

  private async write(name: string, request: Request): Promise<Response> {
    const ifMatch = request.headers.get("If-Match");
    const body = (await request.json()) as { config: TemplateConfigState };
    this.puts.push({ name, ifMatch, body });
    const override = await this.onPut?.(name);
    if (override) return override;
    const stored = this.disk.get(name);
    if (!stored || ifMatch?.replace(/"/g, "") !== stored.revision)
      return Response.json({ detail: "stale" }, { status: 412 });
    const revision = `${name}-w${++this.writes}`;
    this.disk.set(name, { config: body.config, revision });
    return Response.json(body.config, { headers: { ETag: `"${revision}"` } });
  }
}

let server: FakeServer;

beforeEach(() => {
  server = new FakeServer();
  server.disk.set("tee", { config: PHOTO_WARP, revision: "r1" });
  server.disk.set("shirt", { config: PHOTO_WARP, revision: "s1" });
  api.use(server.middleware);
});

afterEach(() => {
  api.eject(server.middleware);
});

function open(name: string | null = "tee", onCatalogChanged = vi.fn()) {
  const hook = renderHook(({ name }) => useTemplateSession(name, { onCatalogChanged }), {
    initialProps: { name },
  });
  return { ...hook, onCatalogChanged };
}

async function opened(name = "tee") {
  const hook = open(name);
  await waitFor(() => expect(hook.result.current.load).toBe("ready"));
  return hook;
}

describe("useTemplateSession", () => {
  it("reads the selected template's document, its revision and its saved time", async () => {
    const { result } = open();
    expect(result.current.load).toBe("loading");
    expect(result.current.config).toBeNull();

    await waitFor(() => expect(result.current.load).toBe("ready"));
    expect(result.current.config).toEqual(PHOTO_WARP);
    expect(result.current.saved).toEqual(PHOTO_WARP);
    expect(result.current.dirty).toBe(false);
    expect(result.current.calibrationRevision).toBe("r1");
    expect(result.current.save).toEqual({ kind: "saved", savedAt: Date.parse(MODIFIED_AT) });
  });

  it("is ready with no config for a folder with no template.yaml", async () => {
    const { result } = open("brand-new");

    await waitFor(() => expect(result.current.load).toBe("ready"));
    expect(result.current.config).toBeNull();
    expect(result.current.save).toEqual({ kind: "idle" });
  });

  it("reports a document that cannot be read as an error", async () => {
    server.middleware.onRequest = () => {
      throw new TypeError("network");
    };
    const { result } = open();

    await waitFor(() => expect(result.current.load).toBe("error"));
  });

  it("has nothing open while no template is selected", () => {
    const { result } = open(null);

    expect(result.current.load).toBe("none");
    expect(result.current.dirty).toBe(false);
  });

  it("is dirty after an edit and clean again once it is undone, without saving", async () => {
    const clock = controlledClock();
    const { result } = await opened();

    act(() => result.current.update(edited(PHOTO_WARP, 7)));
    expect(result.current.dirty).toBe(true);
    // Same document, keys in another order: not an edit.
    const { renderer, bounding_box, kind } = PHOTO_WARP as typeof SINGLE;
    act(() => result.current.update({ renderer, bounding_box, colour: null, kind }));
    expect(result.current.dirty).toBe(false);

    await clock.advance(AUTOSAVE_DEBOUNCE_MS);
    expect(server.puts).toHaveLength(0);
  });

  it("saves a run of edits as one PUT over the read revision once they settle", async () => {
    const clock = controlledClock();
    const { result, onCatalogChanged } = await opened();

    act(() => result.current.update(edited(PHOTO_WARP, 1)));
    await clock.advance(AUTOSAVE_DEBOUNCE_MS - 50);
    act(() => result.current.update(edited(PHOTO_WARP, 2)));
    await clock.advance(AUTOSAVE_DEBOUNCE_MS - 50);
    expect(server.puts).toHaveLength(0);

    await clock.advance(50);
    await waitFor(() => expect(result.current.save.kind).toBe("saved"));
    expect(server.puts).toEqual([
      {
        name: "tee",
        ifMatch: '"r1"',
        body: { request_id: expect.any(String), config: edited(PHOTO_WARP, 2), mask_edits: [] },
      },
    ]);
    expect(result.current.dirty).toBe(false);
    expect(result.current.saved).toEqual(edited(PHOTO_WARP, 2));
    expect(result.current.calibrationRevision).toBe("tee-w1");
    expect(onCatalogChanged).toHaveBeenCalledWith("tee");
  });

  it("keeps one save in flight and sends the next over the revision it returned", async () => {
    const { result } = await opened();
    const first = deferred<null>();
    server.onPut = async () => {
      if (server.puts.length === 1) await first.promise;
      return undefined;
    };

    act(() => result.current.update(edited(PHOTO_WARP, 1)));
    let inFlight!: Promise<void>;
    act(() => {
      inFlight = result.current.flush();
    });
    await waitFor(() => expect(result.current.save.kind).toBe("saving"));
    act(() => result.current.update(edited(PHOTO_WARP, 2)));
    let second!: Promise<void>;
    act(() => {
      second = result.current.flush();
    });
    await Promise.resolve();
    expect(server.puts).toHaveLength(1);

    first.resolve(null);
    await act(() => Promise.all([inFlight, second]));
    expect(server.puts.map((put) => put.ifMatch)).toEqual(['"r1"', '"tee-w1"']);
    expect(server.disk.get("tee")?.config).toEqual(edited(PHOTO_WARP, 2));
    expect(result.current.save.kind).toBe("saved");
  });

  it("writes an unchanged document when approved, where a flush sends nothing", async () => {
    const { result } = await opened();

    await act(() => result.current.flush());
    expect(server.puts).toHaveLength(0);
    await act(() => result.current.approve());

    expect(server.puts).toEqual([
      expect.objectContaining({
        ifMatch: '"r1"',
        body: expect.objectContaining({ config: PHOTO_WARP }),
      }),
    ]);
    expect(result.current.save.kind).toBe("saved");
  });

  it("flushes a pending edit on a template switch, before reading the next template", async () => {
    const { result, rerender, onCatalogChanged } = await opened();

    act(() => result.current.update(edited(PHOTO_WARP, 3)));
    rerender({ name: "shirt" });
    // Never the previous template's draft under the new name.
    expect(result.current.load).toBe("loading");
    expect(result.current.config).toBeNull();

    await waitFor(() => expect(result.current.load).toBe("ready"));
    expect(server.disk.get("tee")?.config).toEqual(edited(PHOTO_WARP, 3));
    expect(server.puts[0]?.ifMatch).toBe('"r1"');
    expect(server.log.indexOf("PUT /api/templates/tee/config")).toBeLessThan(
      server.log.lastIndexOf("GET /api/templates/shirt/config"),
    );
    expect(result.current.calibrationRevision).toBe("s1");
    expect(result.current.dirty).toBe(false);
    // The rail refreshes, but is not pulled back to the template just left.
    expect(onCatalogChanged).toHaveBeenCalledWith(undefined);
  });

  it("flushes a pending edit on unmount", async () => {
    const { result, unmount } = await opened();

    act(() => result.current.update(edited(PHOTO_WARP, 4)));
    unmount();

    await waitFor(() => expect(server.disk.get("tee")?.config).toEqual(edited(PHOTO_WARP, 4)));
  });

  it("reports a save over a revision the disk has moved past as a conflict, until reloaded", async () => {
    const clock = controlledClock();
    const { result } = await opened();
    server.disk.set("tee", { config: edited(PHOTO_WARP, 9), revision: "external" });

    act(() => result.current.update(edited(PHOTO_WARP, 5)));
    await clock.advance(AUTOSAVE_DEBOUNCE_MS);
    await waitFor(() => expect(result.current.save.kind).toBe("conflict"));
    expect(result.current.save).toEqual({
      kind: "conflict",
      message: "Template changed elsewhere. Reload before saving.",
    });
    // The edit stays on screen; nothing on disk changed.
    expect(result.current.config).toEqual(edited(PHOTO_WARP, 5));
    expect(server.disk.get("tee")?.revision).toBe("external");

    act(() => result.current.reload());
    expect(result.current.load).toBe("loading");
    await waitFor(() => expect(result.current.load).toBe("ready"));
    expect(result.current.config).toEqual(edited(PHOTO_WARP, 9));
    expect(result.current.calibrationRevision).toBe("external");
    expect(result.current.save.kind).toBe("saved");
    expect(result.current.dirty).toBe(false);
  });

  it("reports a 409 as the same conflict", async () => {
    const { result } = await opened();
    server.onPut = () => Response.json({ detail: "superseded" }, { status: 409 });

    act(() => result.current.update(edited(PHOTO_WARP, 5)));
    await act(() => result.current.flush());

    expect(result.current.save.kind).toBe("conflict");
  });

  it("reports any other refusal as a failure the next save retries", async () => {
    const { result } = await opened();
    server.onPut = () => Response.json({ detail: "boom" }, { status: 500 });
    act(() => result.current.update(edited(PHOTO_WARP, 6)));

    await act(() => result.current.flush());
    expect(result.current.save).toEqual({
      kind: "failed",
      message: "could not save template.yaml",
    });
    expect(result.current.dirty).toBe(true);

    server.onPut = null;
    await act(() => result.current.flush());
    expect(result.current.save.kind).toBe("saved");
    expect(server.puts.map((put) => put.ifMatch)).toEqual(['"r1"', '"r1"']);
  });

  describe("mask edits", () => {
    it("are sent once, and consumed only when their save commits", async () => {
      const { result } = await opened();
      const first = deferred<null>();
      server.onPut = async () => {
        if (server.puts.length === 1) await first.promise;
        return undefined;
      };
      const one = stroke(1);
      const two = stroke(2);

      act(() => result.current.setMaskEdits([{ placement_id: null, operations: [one] }]));
      expect(result.current.dirty).toBe(true);
      let inFlight!: Promise<void>;
      act(() => {
        inFlight = result.current.flush();
      });
      await waitFor(() => expect(server.puts).toHaveLength(1));
      // The editor appends to the list it last rendered, which still holds
      // the stroke now in flight.
      act(() => result.current.setMaskEdits([{ placement_id: null, operations: [one, two] }]));
      expect(result.current.maskEdits).toEqual([{ placement_id: null, operations: [one, two] }]);

      first.resolve(null);
      await act(() => inFlight);
      await waitFor(() =>
        expect(result.current.maskEdits).toEqual([{ placement_id: null, operations: [two] }]),
      );
      await act(() => result.current.flush());

      expect(server.puts.map((put) => put.body.mask_edits)).toEqual([
        [{ placement_id: null, operations: [one] }],
        [{ placement_id: null, operations: [two] }],
      ]);
      expect(result.current.maskEdits).toEqual([]);
      expect(result.current.dirty).toBe(false);

      // A committed stroke handed back again is not news.
      act(() => result.current.setMaskEdits([{ placement_id: null, operations: [one, two] }]));
      expect(result.current.dirty).toBe(false);
    });

    it("stay pending when their save fails, and go with the retry", async () => {
      const { result } = await opened();
      server.onPut = () => Response.json({ detail: "boom" }, { status: 500 });
      const edits: MaskEdit[] = [{ placement_id: null, operations: [stroke(1)] }];
      act(() => result.current.setMaskEdits(edits));

      await act(() => result.current.flush());
      expect(result.current.maskEdits).toEqual(edits);

      server.onPut = null;
      await act(() => result.current.flush());
      expect(server.puts.map((put) => put.body.mask_edits)).toEqual([edits, edits]);
      expect(result.current.maskEdits).toEqual([]);
    });

    it("are dropped by a reload", async () => {
      const { result } = await opened();
      act(() => result.current.setMaskEdits([{ placement_id: null, operations: [stroke(1)] }]));

      act(() => result.current.reload());
      await waitFor(() => expect(result.current.load).toBe("ready"));

      expect(result.current.maskEdits).toEqual([]);
      expect(server.puts).toHaveLength(0);
    });
  });

  describe("a pending preview", () => {
    it("holds a Marigold draft's autosave and sends it the moment the frame lands", async () => {
      server.disk.set("tee", { config: SINGLE, revision: "r1" });
      const clock = controlledClock();
      const { result } = await opened();

      act(() => result.current.setPreviewPending(true));
      act(() => result.current.update(edited(SINGLE, 8)));
      await clock.advance(AUTOSAVE_DEBOUNCE_MS * 3);
      expect(server.puts).toHaveLength(0);

      act(() => result.current.setPreviewPending(false));
      await waitFor(() => expect(server.puts).toHaveLength(1));
      expect(server.puts[0]?.body.config).toEqual(edited(SINGLE, 8));
    });

    it("also pauses preparation reads, which resume with a fresh one", async () => {
      server.disk.set("tee", { config: SINGLE, revision: "r1" });
      const { result } = await opened();
      await waitFor(() => expect(result.current.preparation).not.toBeNull());
      const reads = () => server.log.filter((line) => line.endsWith("/preparation")).length;
      const before = reads();

      act(() => result.current.setPreviewPending(true));
      await act(async () => window.dispatchEvent(new Event("focus")));
      expect(reads()).toBe(before);

      act(() => result.current.setPreviewPending(false));
      await waitFor(() => expect(reads()).toBeGreaterThan(before));
    });

    it("does not hold a Photo warp draft", async () => {
      const clock = controlledClock();
      const { result } = await opened();

      act(() => result.current.setPreviewPending(true));
      act(() => result.current.update(edited(PHOTO_WARP, 8)));
      await clock.advance(AUTOSAVE_DEBOUNCE_MS);

      await waitFor(() => expect(server.puts).toHaveLength(1));
    });
  });

  describe("prepare", () => {
    it("saves the draft first, then queues the revision the server holds", async () => {
      const { result, onCatalogChanged } = await opened();
      act(() => result.current.update({ ...PHOTO_WARP, renderer: MARIGOLD }));

      await act(() => result.current.prepare());

      expect(server.puts).toHaveLength(1);
      expect(server.log.indexOf("PUT /api/templates/tee/config")).toBeLessThan(
        server.log.indexOf("POST /api/preparation/jobs"),
      );
      expect(server.jobs).toEqual([
        expect.objectContaining({ template: "tee", action: "prepare", config_revision: "r1" }),
      ]);
      expect(result.current.preparing).toBe(false);
      expect(result.current.preparationError).toBe("");
      expect(onCatalogChanged).toHaveBeenLastCalledWith();
    });

    it("refuses to queue when the save is refused", async () => {
      const { result } = await opened();
      server.disk.set("tee", { config: PHOTO_WARP, revision: "external" });
      act(() => result.current.update(edited(PHOTO_WARP, 1)));

      await act(() => result.current.prepare());

      expect(server.jobs).toEqual([]);
      expect(result.current.preparationError).toBe(
        "Template changed elsewhere. Reload before saving.",
      );
      expect(result.current.save.kind).toBe("conflict");
    });

    it("drops the mask edits of placements whose photo changed when resetting their masks", async () => {
      const { result } = await opened();
      server.preparation = {
        ...server.preparation,
        placements: [
          {
            placement_id: null,
            mask_available: false,
            mask_reason: "photo mismatch",
            undo_count: 0,
          },
        ],
      };
      act(() => result.current.reloadPreparation());
      await waitFor(() =>
        expect(result.current.preparation?.placements[0]?.mask_available).toBe(false),
      );
      act(() => result.current.setMaskEdits([{ placement_id: null, operations: [stroke(1)] }]));

      await act(() => result.current.prepare("prepare_again", true));

      expect(result.current.maskEdits).toEqual([]);
      expect(server.puts).toHaveLength(0);
      expect(server.jobs).toEqual([
        expect.objectContaining({ action: "prepare_again", reset_masks_for_photo: true }),
      ]);
    });

    it("names the previous job when retrying", async () => {
      server.preparation = {
        ...server.preparation,
        latest_job: job({ id: "failed", phase: "failed" }),
      };
      const { result } = await opened();

      await act(() => result.current.prepare("retry"));

      expect(server.jobs).toEqual([expect.objectContaining({ previous_job: "failed" })]);
    });

    it("cancels the active job", async () => {
      server.preparation = { ...server.preparation, active_job: job({ phase: "running" }) };
      const { result } = await opened();
      await waitFor(() => expect(result.current.preparation?.active_job).not.toBeNull());

      await act(() => result.current.cancelPreparation());

      expect(server.log).toContain("DELETE /api/preparation/jobs/job-1");
      expect(result.current.preparationError).toBe("");
    });
  });

  describe("the prepared-revision baseline", () => {
    /** Prepares, then completes the job the way the coordinator does: by
     * writing template.yaml again, which moves its revision. */
    async function preparedAndCompleted(diskConfig: TemplateConfigState = PHOTO_WARP) {
      const hook = await opened();
      await act(() => hook.result.current.prepare());
      server.disk.set("tee", { config: diskConfig, revision: "prepared" });
      server.preparation = {
        ...server.preparation,
        config_revision: "prepared",
        latest_job: job({ phase: "completed", config_revision: "prepared" }),
      };
      act(() => hook.result.current.reloadPreparation());
      await waitFor(() =>
        expect(hook.result.current.preparation?.config_revision).toBe("prepared"),
      );
      return hook;
    }

    it("moves to this session's own completed preparation and is what the next save names", async () => {
      const { result } = await preparedAndCompleted();
      await waitFor(() => expect(result.current.calibrationRevision).toBe("prepared"));

      act(() => result.current.update(edited(PHOTO_WARP, 2)));
      await act(() => result.current.flush());

      expect(result.current.save.kind).toBe("saved");
      expect(server.puts.at(-1)?.ifMatch).toBe('"prepared"');
    });

    it("is not adopted when the disk no longer holds what this session saved", async () => {
      const { result } = await preparedAndCompleted(edited(PHOTO_WARP, 9));

      act(() => result.current.update(edited(PHOTO_WARP, 2)));
      await act(() => result.current.flush());

      expect(server.puts.at(-1)?.ifMatch).toBe('"r1"');
      expect(result.current.save.kind).toBe("conflict");
    });

    it("ignores a completion this session did not queue", async () => {
      const { result } = await opened();
      server.disk.set("tee", { config: PHOTO_WARP, revision: "prepared" });
      server.preparation = {
        ...server.preparation,
        config_revision: "prepared",
        latest_job: job({ id: "other-tab", phase: "completed", config_revision: "prepared" }),
      };
      act(() => result.current.reloadPreparation());
      await waitFor(() => expect(result.current.preparation?.config_revision).toBe("prepared"));

      expect(result.current.calibrationRevision).toBe("r1");
      act(() => result.current.update(edited(PHOTO_WARP, 2)));
      await act(() => result.current.flush());
      expect(result.current.save.kind).toBe("conflict");
    });
  });
});
