import { useEffect, useState } from "react";
import { getMarketSnapshot } from "../../../api/market";
import type { MarketSnapshot } from "../../../types";
import type { AiRun } from "../aiSeo/useAiRun";
import type { MarketPanelState } from "./MarketListingsPanel";

/** What the panel reads from the listing's AI run. */
export type MarketRun = Pick<AiRun, "busy" | "steps" | "queries" | "market">;

interface Known {
  listing: string;
  snapshot: MarketSnapshot | null;
  /** Came from a run's `market` event, which is newer than any `GET`. */
  fromRun: boolean;
}

function shown(snapshot: MarketSnapshot): MarketPanelState {
  return snapshot.empty
    ? { kind: "empty", queries: snapshot.queries }
    : { kind: "ready", snapshot };
}

/**
 * Which state the top listings panel is in, or `null` for no panel at all
 * (docs/ui-market-seo-interactions.md, *Panel states*):
 *
 * - **loading** while the run's market node is active -- even over a saved
 *   snapshot, since a re-run drops to it straight away -- with the searches
 *   once the `queries` event has named them;
 * - **hidden** when the market node failed while this editor was watching
 *   the run. The reason is a toast, not a note in this column. The snapshot
 *   on disk is untouched, so a reload -- which only replays the failure --
 *   shows the previous results again;
 * - otherwise the newest search this editor knows of: the run's `market`
 *   event, or the snapshot `GET …/market` answered on mount. A search that
 *   found nothing is the **empty** note; no search at all is no panel.
 */
export function useMarketPanel(listing: string, run: MarketRun): MarketPanelState | null {
  const [known, setKnown] = useState<Known>({ listing, snapshot: null, fromRun: false });
  const [seen, setSeen] = useState<MarketSnapshot | null>(null);
  const [watched, setWatched] = useState(false);

  if (run.busy && !watched) setWatched(true);
  if (run.market !== seen) {
    setSeen(run.market);
    if (run.market !== null) setKnown({ listing, snapshot: run.market, fromRun: true });
  }

  useEffect(() => {
    if (listing === "") return;
    let current = true;
    getMarketSnapshot(listing)
      .then((snapshot) => {
        if (!current) return;
        setKnown((k) =>
          k.listing === listing && k.fromRun ? k : { listing, snapshot, fromRun: false },
        );
      })
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [listing]);

  const step = run.steps.find((s) => s.id === "market");
  if (step?.state === "active") return { kind: "loading", queries: run.queries };
  // A failure the editor watched would otherwise become the panel's own
  // error note. The reason is the toast; this column goes away until a
  // reload brings the saved snapshot back.
  if (step?.state === "failed" && watched) return null;
  const snapshot = run.market ?? (known.listing === listing ? known.snapshot : null);
  return snapshot === null ? null : shown(snapshot);
}
