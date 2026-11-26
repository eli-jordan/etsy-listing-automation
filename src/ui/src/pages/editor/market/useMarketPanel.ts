import { useEffect, useState } from "react";
import { getMarketSnapshot } from "../../../api/market";
import type { MarketSnapshot } from "../../../types";
import type { AiRun } from "../aiSeo/useAiRun";
import type { MarketPanelState } from "./MarketListingsPanel";

export type MarketRun = Pick<AiRun, "busy" | "steps" | "queries" | "market">;

interface Known {
  listing: string;
  snapshot: MarketSnapshot | null;
  fromRun: boolean;
}

function shown(snapshot: MarketSnapshot): MarketPanelState {
  return snapshot.empty
    ? { kind: "empty", queries: snapshot.queries }
    : { kind: "ready", snapshot };
}

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
  if (step?.state === "failed" && watched) return null;
  const snapshot = run.market ?? (known.listing === listing ? known.snapshot : null);
  return snapshot === null ? null : shown(snapshot);
}
