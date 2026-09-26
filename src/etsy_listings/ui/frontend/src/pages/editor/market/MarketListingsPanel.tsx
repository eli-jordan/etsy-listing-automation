import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { EyeIcon } from "@phosphor-icons/react/dist/csr/Eye";
import { HeartIcon } from "@phosphor-icons/react/dist/csr/Heart";
import { MagnifyingGlassIcon } from "@phosphor-icons/react/dist/csr/MagnifyingGlass";
import { StarIcon } from "@phosphor-icons/react/dist/csr/Star";
import { StorefrontIcon } from "@phosphor-icons/react/dist/csr/Storefront";
import { WarningCircleIcon } from "@phosphor-icons/react/dist/csr/WarningCircle";
import { useEffect, useState } from "react";
import type {
  MarketSnapshot,
  PhraseScore,
  ScoredListing,
  SeoProposalResponse,
} from "../../../types";
import { timeAgo } from "../timeAgo";

/**
 * The right-hand column of Listing Details (docs/ui-market-seo-interactions.md,
 * section 2; market-seo.md, *UI*): what the last market search found, read
 * from the snapshot so it survives a reload. Read-only by design.
 *
 * It has a second job: showing the seller *why* the suggestions read as they
 * do. The top eight are what the proposal saw verbatim; all of them fed the
 * phrase list.
 */

export type MarketPanelState =
  | { kind: "loading"; queries: string[] | null }
  | { kind: "ready"; snapshot: MarketSnapshot }
  | { kind: "empty"; queries: string[] }
  | { kind: "failed"; reason: string };

/** How many of the scored listings the proposal sees verbatim (market-seo.md). */
const EXAMPLES = 8;

function compact(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k` : String(n);
}

/** Views and favourites per day: whole numbers once they are big enough for
 * the tenths to be noise. */
function perDay(n: number): string {
  return n >= 10 ? String(Math.round(n)) : n.toFixed(1);
}

/** "1 listing", "4 listings". */
function listings(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

/** A reason as a sentence, so "Nothing changed." can follow it. */
function sentence(reason: string): string {
  const trimmed = reason.trim();
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

/** Ages "searched a moment ago" without a new search, as `SavedAgo` does. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(id);
  }, []);
  return now;
}

/** The Etsy searches AI Mode wrote from the brief, as a sentence rather than
 * chips, so they can't be taken for tags. */
function Queries({ queries, searching }: { queries: string[]; searching?: boolean }) {
  return (
    <p className={searching ? "mkt-queries mkt-queries--searching" : "mkt-queries"}>
      <span className="mkt-queries__label">
        <MagnifyingGlassIcon weight="bold" aria-hidden="true" />{" "}
        {searching ? "Searching Etsy for" : "Searched Etsy for"}
      </span>{" "}
      {queries.map((q, i) => (
        <span key={q}>
          {i > 0 && (i === queries.length - 1 ? " and " : ", ")}
          <span className="mkt-query">“{q}”</span>
        </span>
      ))}
    </p>
  );
}

/** The listing's first image at 40px, or a plain tile when it has none or it
 * fails to load -- a broken-image icon in a list of photos reads as a fault. */
function Thumb({ url }: { url: string | null }) {
  const [broken, setBroken] = useState(false);
  if (url === null || broken) return <span className="mkt-thumb mkt-thumb--none" />;
  return (
    <img className="mkt-thumb" src={url} alt="" loading="lazy" onError={() => setBroken(true)} />
  );
}

function ListingRow({
  item,
  open,
  onToggle,
}: {
  item: ScoredListing;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <li className={open ? "mkt-row mkt-row--open" : "mkt-row"}>
      <button className="mkt-row__main" type="button" aria-expanded={open} onClick={onToggle}>
        <span className="mkt-row__rank">{item.rank}</span>
        <Thumb url={item.thumbnail_url} />
        <span className="mkt-row__text">
          <span className="mkt-row__title">{item.title}</span>
          <span className="mkt-row__shop">
            {item.own_shop ? (
              <span className="mkt-own">
                <StorefrontIcon weight="bold" aria-hidden="true" /> Your shop
              </span>
            ) : (
              item.shop_name
            )}
            {item.shop_rating !== null && (
              <>
                <span aria-hidden="true">·</span>
                <StarIcon weight="fill" className="mkt-star" aria-hidden="true" />{" "}
                {item.shop_rating.toFixed(1)}
              </>
            )}
          </span>
          <span className="mkt-row__metrics">
            <span title="Reviews on this listing">
              <StarIcon weight="bold" aria-hidden="true" /> {compact(item.reviews)}
            </span>
            {item.favourites_per_day !== null && (
              <span title="Favourites per day">
                <HeartIcon weight="bold" aria-hidden="true" /> {perDay(item.favourites_per_day)}/d
              </span>
            )}
            {item.views_per_day !== null && (
              <span title="Views per day">
                <EyeIcon weight="bold" aria-hidden="true" /> {perDay(item.views_per_day)}/d
              </span>
            )}
          </span>
        </span>
        <span className="mkt-score" title={`Market score ${item.score} of 100`}>
          <span className="mkt-score__value">{item.score}</span>
          <span className="mkt-score__bar">
            <span style={{ width: `${item.score}%` }} />
          </span>
        </span>
        <CaretDownIcon weight="bold" className="mkt-row__caret" aria-hidden="true" />
      </button>
      {open && (
        <div className="mkt-row__detail">
          {item.lead && <p className="mkt-row__lead">“{item.lead}”</p>}
          {item.tags.length > 0 && (
            <div className="mkt-row__tags">
              {item.tags.map((t) => (
                <span className="mkt-tag" key={t}>
                  {t}
                </span>
              ))}
            </div>
          )}
          <a
            className="mkt-link"
            href={`https://www.etsy.com/listing/${item.listing_id}`}
            target="_blank"
            rel="noreferrer"
          >
            Open on Etsy <ArrowSquareOutIcon weight="bold" aria-hidden="true" />
          </a>
        </div>
      )}
    </li>
  );
}

/** The top eight -- what the proposal was shown verbatim -- then, on
 * request, the rest that only fed the phrase list. One row open at a time;
 * revealing the rest is one-way. */
function Listings({ snapshot }: { snapshot: MarketSnapshot }) {
  const [open, setOpen] = useState<number | null>(null);
  const [all, setAll] = useState(false);
  const examples = snapshot.listings.slice(0, EXAMPLES);
  const rest = snapshot.listings.slice(EXAMPLES);
  const row = (item: ScoredListing) => (
    <ListingRow
      item={item}
      key={item.listing_id}
      open={open === item.listing_id}
      onToggle={() => setOpen(open === item.listing_id ? null : item.listing_id)}
    />
  );
  return (
    <>
      <p className="mkt-group">Examples shown to AI Mode</p>
      <ol className="mkt-list">{examples.map(row)}</ol>
      {rest.length > 0 &&
        (all ? (
          <>
            <p className="mkt-group">Also scored</p>
            <ol className="mkt-list">{rest.map(row)}</ol>
          </>
        ) : (
          <button className="mkt-more" type="button" onClick={() => setAll(true)}>
            Show {listings(rest.length, "more scored listing")}
          </button>
        ))}
    </>
  );
}

/** What the phrase ticks are read from. */
export type Suggestions = Pick<SeoProposalResponse, "titles" | "tags" | "description_leads">;

/** The phrase-tick rule (docs/ui-market-seo-interactions.md, *Phrases view*):
 * the phrase is one of the suggested tags, or a suggested title or lead
 * contains it, ignoring case. */
function inSuggestions(phrase: string, suggestions: Suggestions): boolean {
  const wanted = phrase.toLowerCase();
  return (
    suggestions.tags.some((tag) => tag.toLowerCase() === wanted) ||
    [...suggestions.titles, ...suggestions.description_leads].some((text) =>
      text.toLowerCase().includes(wanted),
    )
  );
}

function Phrases({
  phrases,
  suggestions,
}: {
  phrases: PhraseScore[];
  suggestions: Suggestions | null;
}) {
  return (
    <>
      <p className="mkt-group">Tags the top listings share, strongest first</p>
      <ol className="mkt-phrases">
        {phrases.map((p) => (
          <li className="mkt-phrase" key={p.phrase}>
            <span className="mkt-phrase__text">
              {suggestions !== null && inSuggestions(p.phrase, suggestions) && (
                <CheckIcon
                  weight="bold"
                  className="mkt-phrase__used"
                  role="img"
                  aria-label="In your suggestions"
                />
              )}
              {p.phrase}
            </span>
            <span className="mkt-phrase__count">{listings(p.listings, "listing")}</span>
            <span className="mkt-score__bar">
              <span style={{ width: `${Math.round(p.score * 100)}%` }} />
            </span>
          </li>
        ))}
      </ol>
      {suggestions !== null && (
        <p className="mkt-foot">Ticked phrases made it into the current suggestions.</p>
      )}
    </>
  );
}

type View = "listings" | "phrases";

/** Listings | Phrases, as the app's one segmented control (`.seg`). */
function ViewSwitch({ view, onChange }: { view: View; onChange: (view: View) => void }) {
  return (
    <div className="seg mkt-seg" role="tablist" aria-label="Market view">
      {(["listings", "phrases"] as const).map((option) => (
        <button
          key={option}
          type="button"
          role="tab"
          aria-selected={view === option}
          className={`seg-opt${view === option ? " seg-opt--on" : ""}`}
          onClick={() => onChange(option)}
        >
          {option === "listings" ? "Listings" : "Phrases"}
        </button>
      ))}
    </div>
  );
}

export function MarketListingsPanel({
  state,
  proposal,
}: {
  state: MarketPanelState;
  /** The pending proposal, whose words tick the phrases they share; `null`
   * when there is none. */
  proposal: Suggestions | null;
}) {
  const now = useNow();
  const [view, setView] = useState<View>("listings");
  return (
    <aside className="mkt-panel" aria-label="Top listings on Etsy">
      <header className="mkt-head">
        <h2 className="mkt-head__title">Top listings on Etsy</h2>
        {state.kind === "ready" && (
          <span className="mkt-head__meta">
            {state.snapshot.scored} scored from {state.snapshot.found} found · searched{" "}
            {timeAgo(Date.parse(state.snapshot.searched_at), now)}
          </span>
        )}
      </header>

      {state.kind === "loading" && (
        <>
          {state.queries === null ? (
            <p className="mkt-queries mkt-queries--searching">
              <span className="mkt-queries__label">
                <MagnifyingGlassIcon weight="bold" aria-hidden="true" /> Choosing Etsy searches from
                the brief…
              </span>
            </p>
          ) : (
            <Queries queries={state.queries} searching />
          )}
          <ol className="mkt-list" aria-hidden="true">
            {[0, 1, 2, 3, 4].map((i) => (
              <li className="mkt-row mkt-row--skeleton" key={i}>
                <span className="mkt-skel mkt-skel--thumb" />
                <span className="mkt-skel-lines">
                  <span className="mkt-skel" />
                  <span className="mkt-skel mkt-skel--short" />
                </span>
              </li>
            ))}
          </ol>
        </>
      )}

      {state.kind === "empty" && (
        <>
          <Queries queries={state.queries} />
          <div className="mkt-note">
            <strong>No comparable listings found</strong>
            <span>
              Etsy returned nothing for these searches, even without the age filter. The suggestions
              were written from the design and brief alone.
            </span>
          </div>
        </>
      )}

      {state.kind === "failed" && (
        <div className="mkt-note mkt-note--failed">
          <strong>
            <WarningCircleIcon weight="bold" aria-hidden="true" /> Etsy market search failed
          </strong>
          <span>{sentence(state.reason)} Nothing changed. Run AI Mode again to retry.</span>
        </div>
      )}

      {state.kind === "ready" && (
        <>
          <Queries queries={state.snapshot.queries} />
          <ViewSwitch view={view} onChange={setView} />
          {view === "listings" ? (
            <Listings snapshot={state.snapshot} />
          ) : (
            <Phrases phrases={state.snapshot.phrases} suggestions={proposal} />
          )}
        </>
      )}
    </aside>
  );
}
