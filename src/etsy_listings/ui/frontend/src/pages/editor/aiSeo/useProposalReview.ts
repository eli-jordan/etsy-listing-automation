import { useCallback, useEffect, useRef, useState } from "react";
import { getListingProposal, resolveListingProposal } from "../../../api/seo";
import type { SaveState } from "../../../hooks/useAutosave";
import type {
  AiRunEvent,
  AiRunSummary,
  ListingDetail,
  ListingProposal,
  ProposalResolution,
} from "../../../types";
import { canToggleTag } from "./aiSeoTags";

type Section = keyof ProposalResolution;
type Choice = "accepted" | "dismissed";
interface ResolutionJob {
  generation: string;
  section: Section;
  state: Choice;
  token: number;
}
interface ReviewSession {
  name: string;
  record: ListingProposal | null;
  pending: Partial<Record<Section, ResolutionJob | undefined>>;
  queue: ResolutionJob[];
  active: boolean;
  version: number;
  disposed: boolean;
}

function settleResolution(current: ReviewSession, job: ResolutionJob): boolean {
  if (current.disposed || current.record?.generated_at !== job.generation) return false;
  if (current.pending[job.section]?.token === job.token) current.pending[job.section] = undefined;
  return true;
}

/**
 * A41: one owner for proposal identity, live-event/cache precedence and
 * optimistic drawer resolutions. Resolution writes are serial; pending
 * choices overlay reads until acknowledged, so autosave cannot reopen a
 * drawer while its resolution is still in flight. Accepted content keeps
 * travelling through ordinary autosave, independently of these cache writes.
 */
export function useProposalReview(
  detail: ListingDetail,
  onUpdate: (patch: Record<string, unknown>) => void,
  onFlush: () => void,
  save?: SaveState,
) {
  const session = useRef<ReviewSession | null>(null);
  const editor = useRef({ detail, onUpdate, onFlush });
  const [view, setView] = useState<{ name: string; record: ListingProposal | null }>({
    name: detail.name,
    record: null,
  });
  useEffect(() => {
    editor.current = { detail, onUpdate, onFlush };
  });
  useEffect(() => {
    const current: ReviewSession = {
      name: detail.name,
      record: null,
      pending: {},
      queue: [],
      active: false,
      version: 0,
      disposed: false,
    };
    session.current = current;
    return () => {
      current.disposed = true;
    };
  }, [detail.name]);

  const commit = useCallback((current: ReviewSession, next: ListingProposal | null) => {
    if (current.disposed) return;
    if (next?.generated_at !== current.record?.generated_at) {
      current.pending = {};
      current.queue = [];
    }
    if (next !== null) {
      const resolution = { ...next.resolution };
      for (const job of Object.values(current.pending)) {
        if (job !== undefined) resolution[job.section] = job.state;
      }
      next = { ...next, resolution };
    }
    current.record = next;
    setView({ name: current.name, record: next });
  }, []);

  const read = useCallback(
    (current: ReviewSession) => {
      const version = ++current.version;
      getListingProposal(current.name)
        .then((next) => {
          if (!current.disposed && version === current.version) commit(current, next);
        })
        .catch(() => {});
    },
    [commit],
  );
  const refresh = useCallback(() => {
    const current = session.current;
    if (current !== null && !current.disposed) read(current);
  }, [read]);

  const saved = save === undefined || save.kind === "saved";
  const canRead = detail.name !== "" && Object.keys(detail.design).length > 0 && saved;
  useEffect(() => {
    if (canRead) refresh();
  }, [canRead, detail.name, detail.modified_at, save, refresh]);

  const onProposal = useCallback(
    (event: Extract<AiRunEvent, { type: "proposal" }>, source: AiRunSummary) => {
      const current = session.current;
      // Finished-run replay is history. The server record owns resolutions.
      if (current === null || source.listing !== current.name || source.phase !== "running") return;
      ++current.version;
      const { type, seq, ...record } = event;
      void type;
      void seq;
      commit(current, record);
    },
    [commit],
  );

  const drain = useCallback(
    function send(current: ReviewSession): void {
      // Navigation stops observations, but already-chosen resolutions still persist.
      if (current.active) return;
      const job = current.queue.shift();
      if (job === undefined) return;
      current.active = true;
      const version = ++current.version;
      resolveListingProposal(current.name, {
        generated_at: job.generation,
        [job.section]: job.state,
      })
        .then((next) => {
          if (!settleResolution(current, job)) return;
          const changedWhileSaving = version !== current.version;
          ++current.version;
          if (next === null) read(current);
          else if (changedWhileSaving && current.record !== null) {
            // A later read may have judged this proposal stale. Acknowledge
            // the section without replacing that newer comparison, then
            // reread in case a save's request was still in flight.
            commit(current, {
              ...current.record,
              resolution: { ...current.record.resolution, [job.section]: job.state },
            });
            read(current);
          } else commit(current, next);
        })
        .catch(() => {
          if (settleResolution(current, job)) read(current);
        })
        .finally(() => {
          current.active = false;
          send(current);
        });
    },
    [commit, read],
  );

  const resolve = useCallback(
    (section: Section, state: Choice) => {
      const current = session.current;
      if (current === null || current.disposed || current.record === null) return;
      const job = {
        generation: current.record.generated_at,
        section,
        state,
        token: ++current.version,
      };
      current.pending[section] = job;
      current.queue.push(job);
      commit(current, current.record);
      drain(current);
    },
    [commit, drain],
  );

  const chooseTitle = useCallback(
    (value: string) => {
      editor.current.onUpdate({ etsy: { title: value } });
      editor.current.onFlush();
      resolve("title", "accepted");
    },
    [resolve],
  );
  const chooseLead = useCallback(
    (value: string) => {
      editor.current.onUpdate({
        etsy: { description: { ...editor.current.detail.etsy.description, lead: value } },
      });
      editor.current.onFlush();
      resolve("lead", "accepted");
    },
    [resolve],
  );
  const toggleTag = useCallback((tag: string) => {
    const tags = editor.current.detail.etsy.tags;
    if (!canToggleTag(tags, tag)) return;
    editor.current.onUpdate({
      etsy: { tags: tags.includes(tag) ? tags.filter((t) => t !== tag) : [...tags, tag] },
    });
    editor.current.onFlush();
  }, []);
  const acceptBestTags = useCallback(() => {
    const record = session.current?.record;
    if (record === null || record === undefined) return;
    editor.current.onUpdate({ etsy: { tags: record.proposal.tags.slice(0, 13) } });
    editor.current.onFlush();
    resolve("tags", "accepted");
  }, [resolve]);

  const record = view.name === detail.name ? view.record : null;
  const proposal =
    record !== null && Object.values(record.resolution).some((state) => state === "pending")
      ? record
      : null;
  return {
    proposal,
    staleReason: proposal?.stale.is_stale ? proposal.stale.reasons.join(", ") : null,
    onProposal,
    refresh,
    actions: {
      chooseTitle,
      chooseLead,
      toggleTag,
      acceptBestTags,
      rejectTitle: () => resolve("title", "dismissed"),
      rejectLead: () => resolve("lead", "dismissed"),
      closeTags: () => resolve("tags", "dismissed"),
    },
  };
}
