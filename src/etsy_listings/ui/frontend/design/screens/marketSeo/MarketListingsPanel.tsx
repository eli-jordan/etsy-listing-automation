import { ArrowSquareOut, CaretDown, Check, Eye, Heart, MagnifyingGlass, Star, Storefront, WarningCircle } from "@phosphor-icons/react";
import { useState } from "react";

export type MarketListing = {
  id: number;
  rank: number;
  title: string;
  shop: string;
  ownShop?: boolean;
  score: number;
  reviews: number;
  favouritesPerDay: number;
  viewsPerDay: number;
  shopRating: number;
  thumb: { shirt: string; ink: string; motif: "sun" | "peaks" };
  tags: string[];
  lead: string;
};

export type MarketPhrase = { phrase: string; listings: number; score: number; used: boolean };

export type MarketResearch = {
  queries: string[];
  found: number;
  scored: number;
  searchedAgo: string;
  listings: MarketListing[];
  phrases: MarketPhrase[];
};

type PanelState =
  | { kind: "loading"; queries: string[] }
  | { kind: "ready"; research: MarketResearch }
  | { kind: "empty"; queries: string[] }
  | { kind: "failed"; reason: string };

/** How many of the scored listings the proposal sees verbatim (market-seo.md). */
const EXAMPLES = 8;

/** Stand-in product photo: a tee in the listing's colour with its print. */
function TeeThumb({ shirt, ink, motif }: MarketListing["thumb"]) {
  return (
    <svg className="mkt-thumb" viewBox="0 0 48 48" aria-hidden="true">
      <rect width="48" height="48" fill="color-mix(in srgb, var(--color-surface) 70%, white)" />
      <path d="M16 9 12 11 6 16l4 6 4-2v21h20V20l4 2 4-6-6-5-4-2c-1 2.5-3.8 4-8 4s-7-1.5-8-4Z" fill={shirt} stroke="rgba(0,0,0,.18)" strokeWidth=".8" />
      {motif === "sun" ? (
        <g>
          <circle cx="24" cy="25" r="5" fill={ink} />
          <path d="M17 29.5h14M18 31.5h12" stroke={ink} strokeWidth="1.1" />
        </g>
      ) : (
        <path d="m16 31 5-8 3 4 3-6 5 10Z" fill={ink} />
      )}
    </svg>
  );
}

function compact(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k` : String(n);
}

/** The Etsy searches AI Mode wrote from the brief, as a sentence rather than chips. */
function Queries({ queries, searching }: { queries: string[]; searching?: boolean }) {
  return (
    <p className={searching ? "mkt-queries mkt-queries--searching" : "mkt-queries"}>
      <span className="mkt-queries__label"><MagnifyingGlass weight="bold" /> {searching ? "Searching Etsy for" : "Searched Etsy for"}</span>{" "}
      {queries.map((q, i) => (
        <span key={q}>
          {i > 0 && (i === queries.length - 1 ? " and " : ", ")}
          <span className="mkt-query">“{q}”</span>
        </span>
      ))}
    </p>
  );
}

function ListingRow({ item, open, onToggle }: { item: MarketListing; open: boolean; onToggle: () => void }) {
  const url = `https://www.etsy.com/listing/${item.id}`;
  return (
    <li className={open ? "mkt-row mkt-row--open" : "mkt-row"}>
      <button className="mkt-row__main" type="button" aria-expanded={open} onClick={onToggle}>
        <span className="mkt-row__rank">{item.rank}</span>
        <TeeThumb {...item.thumb} />
        <span className="mkt-row__text">
          <span className="mkt-row__title">{item.title}</span>
          <span className="mkt-row__shop">
            {item.ownShop ? <span className="mkt-own"><Storefront weight="bold" /> Your shop</span> : item.shop}
            <span aria-hidden="true">·</span>
            <Star weight="fill" className="mkt-star" /> {item.shopRating.toFixed(1)}
          </span>
          <span className="mkt-row__metrics">
            <span title="Reviews on this listing"><Star weight="bold" /> {compact(item.reviews)}</span>
            <span title="Favourites per day"><Heart weight="bold" /> {item.favouritesPerDay.toFixed(1)}/d</span>
            <span title="Views per day"><Eye weight="bold" /> {item.viewsPerDay}/d</span>
          </span>
        </span>
        <span className="mkt-score" title={`Market score ${item.score} of 100`}>
          <span className="mkt-score__value">{item.score}</span>
          <span className="mkt-score__bar"><span style={{ width: `${item.score}%` }} /></span>
        </span>
        <CaretDown weight="bold" className="mkt-row__caret" />
      </button>
      {open && (
        <div className="mkt-row__detail">
          {item.lead && <p className="mkt-row__lead">“{item.lead}”</p>}
          {item.tags.length > 0 && (
            <div className="mkt-row__tags">
              {item.tags.map((t) => <span className="mkt-tag" key={t}>{t}</span>)}
            </div>
          )}
          <a className="mkt-link" href={url} target="_blank" rel="noreferrer">
            Open on Etsy <ArrowSquareOut weight="bold" />
          </a>
        </div>
      )}
    </li>
  );
}

function Listings({ research, initialOpen }: { research: MarketResearch; initialOpen?: number }) {
  const [open, setOpen] = useState<number | null>(initialOpen ?? null);
  const [all, setAll] = useState(false);
  const examples = research.listings.slice(0, EXAMPLES);
  const rest = research.listings.slice(EXAMPLES);
  const row = (item: MarketListing) => (
    <ListingRow item={item} key={item.id} open={open === item.id} onToggle={() => setOpen(open === item.id ? null : item.id)} />
  );
  return (
    <>
      <p className="mkt-group">Examples shown to AI Mode</p>
      <ol className="mkt-list">{examples.map(row)}</ol>
      {all ? (
        <>
          <p className="mkt-group">Also scored</p>
          <ol className="mkt-list">{rest.map(row)}</ol>
        </>
      ) : (
        <button className="mkt-more" type="button" onClick={() => setAll(true)}>
          Show {research.scored - EXAMPLES} more scored listings
        </button>
      )}
    </>
  );
}

function Phrases({ phrases }: { phrases: MarketPhrase[] }) {
  return (
    <>
      <p className="mkt-group">Tags the top listings share, strongest first</p>
      <ol className="mkt-phrases">
        {phrases.map((p) => (
          <li className="mkt-phrase" key={p.phrase}>
            <span className="mkt-phrase__text">
              {p.used && <Check weight="bold" className="mkt-phrase__used" aria-label="In your suggestions" />}
              {p.phrase}
            </span>
            <span className="mkt-phrase__count">{p.listings} listings</span>
            <span className="mkt-score__bar"><span style={{ width: `${p.score * 100}%` }} /></span>
          </li>
        ))}
      </ol>
      <p className="mkt-foot">Ticked phrases made it into the current suggestions.</p>
    </>
  );
}

/**
 * The right-hand column of Listing Details: what the last market search found,
 * read from the snapshot so it survives a reload. Read-only by design.
 */
export function MarketListingsPanel({
  state,
  initialView = "listings",
  initialOpen,
}: {
  state: PanelState;
  initialView?: "listings" | "phrases";
  initialOpen?: number;
}) {
  const [view, setView] = useState(initialView);

  return (
    <aside className="mkt-panel" aria-label="Similar Etsy Listings">
      <header className="mkt-head">
        <h2 className="mkt-head__title">Similar Etsy Listings</h2>
        {state.kind === "ready" && (
          <span className="mkt-head__meta">
            {state.research.scored} scored from {state.research.found} found · searched {state.research.searchedAgo}
          </span>
        )}
              </header>

      {state.kind === "loading" && (
        <>
          <Queries queries={state.queries} searching />
          <ol className="mkt-list" aria-hidden="true">
            {[0, 1, 2, 3, 4].map((i) => (
              <li className="mkt-row mkt-row--skeleton" key={i}>
                <span className="mkt-skel mkt-skel--thumb" />
                <span className="mkt-skel-lines"><span className="mkt-skel" /><span className="mkt-skel mkt-skel--short" /></span>
              </li>
            ))}
          </ol>
        </>
      )}

      {state.kind === "ready" && (
        <>
          <Queries queries={state.research.queries} />
          <div className="mkt-switch" role="tablist" aria-label="Market view">
            <button role="tab" aria-selected={view === "listings"} className={view === "listings" ? "mkt-switch__opt mkt-switch__opt--on" : "mkt-switch__opt"} onClick={() => setView("listings")} type="button">Listings</button>
            <button role="tab" aria-selected={view === "phrases"} className={view === "phrases" ? "mkt-switch__opt mkt-switch__opt--on" : "mkt-switch__opt"} onClick={() => setView("phrases")} type="button">Phrases</button>
          </div>
          {view === "listings" ? <Listings research={state.research} initialOpen={initialOpen} /> : <Phrases phrases={state.research.phrases} />}
        </>
      )}

      {state.kind === "empty" && (
        <>
          <Queries queries={state.queries} />
          <div className="mkt-note">
            <strong>No comparable listings found</strong>
            <span>Etsy returned nothing for these searches, even without the age filter. The suggestions were written from the design and brief alone.</span>
          </div>
        </>
      )}

      {state.kind === "failed" && (
        <div className="mkt-note mkt-note--failed">
          <strong><WarningCircle weight="bold" /> Etsy market search failed</strong>
          <span>{state.reason} Nothing changed. Run AI Mode again to retry.</span>
        </div>
      )}
    </aside>
  );
}
