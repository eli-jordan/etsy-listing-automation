import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { MARKET_QUERIES, marketSnapshot } from "../../../test/market";
import { MarketListingsPanel } from "./MarketListingsPanel";

/** The right-hand column of Listing Details (docs/ui-market-seo-interactions.md,
 * section 2): what the last market search found, and what AI Mode was shown. */

/** The element, or a failed test saying which one was missing. */
function must<T>(value: T | null | undefined, what: string): T {
  if (value === null || value === undefined) throw new Error(`no ${what}`);
  return value;
}

function panel() {
  return screen.getByRole("complementary", { name: "Top listings on Etsy" });
}

it("says how big and how fresh the sample is, and what was searched", () => {
  const searchedAt = new Date(Date.now() - 5 * 60_000).toISOString();

  render(
    <MarketListingsPanel
      state={{ kind: "ready", snapshot: marketSnapshot({ searched_at: searchedAt }) }}
      proposal={null}
    />,
  );

  expect(within(panel()).getByRole("heading", { name: "Top listings on Etsy" })).toBeVisible();
  expect(panel()).toHaveTextContent("12 scored from 58 found · searched 5 mins ago");
  expect(panel()).toHaveTextContent(
    "Searched Etsy for “retro sunset hiking shirt”, “take a hike t shirt” and “vintage mountain graphic tee”",
  );
});

it("lists the eight examples AI Mode was shown, best first", () => {
  render(
    <MarketListingsPanel state={{ kind: "ready", snapshot: marketSnapshot() }} proposal={null} />,
  );

  const examples = must(within(panel()).getAllByRole("list")[0], "examples list");
  expect(panel()).toHaveTextContent("Examples shown to AI Mode");
  const rows = within(examples).getAllByRole("listitem");
  expect(rows).toHaveLength(8);
  const first = must(rows[0], "first row");
  expect(first).toHaveTextContent("1");
  expect(first).toHaveTextContent("Retro Sunset Hiking Shirt 1");
  expect(first).toHaveTextContent("TrailTees1");
  expect(first).toHaveTextContent("4.8");
  expect(first).toHaveTextContent("94");
  expect(within(first).getByTitle("Market score 94 of 100")).toBeInTheDocument();
  expect(within(first).getByTitle("Reviews on this listing")).toHaveTextContent("10");
  expect(within(first).getByTitle("Favourites per day")).toHaveTextContent("1.5/d");
  expect(within(first).getByTitle("Views per day")).toHaveTextContent("12/d");
});

function ready(snapshot = marketSnapshot()) {
  render(<MarketListingsPanel state={{ kind: "ready", snapshot }} proposal={null} />);
}

function row(n: number): HTMLElement {
  const title = screen.getByText(`Retro Sunset Hiking Shirt ${n}`, { exact: true });
  return must(title.closest("button"), `row ${n}`);
}

it("shows each listing's first image, and a plain tile when there is none", () => {
  ready(marketSnapshot({ scored: 2, edit: { 2: { thumbnail_url: null } } }));

  const image = within(row(1)).getByRole("presentation");
  expect(image.tagName).toBe("IMG");
  expect(image).toHaveAttribute("src", "https://i.etsystatic.com/1/il_170x135.jpg");
  expect(within(row(2)).queryByRole("presentation")).toBeNull();
  expect(row(2).querySelector(".mkt-thumb--none")).not.toBeNull();
});

it("swaps a thumbnail that fails to load for the plain tile", () => {
  ready(marketSnapshot({ scored: 1 }));

  fireEvent.error(within(row(1)).getByRole("presentation"));

  expect(within(row(1)).queryByRole("presentation")).toBeNull();
  expect(row(1).querySelector(".mkt-thumb--none")).not.toBeNull();
});

it("opens one row at a time, showing what AI Mode read from it", async () => {
  const user = userEvent.setup();
  ready();

  await user.click(row(1));

  expect(row(1)).toHaveAttribute("aria-expanded", "true");
  const first = must(row(1).closest("li"), "row 1 item");
  expect(first).toHaveTextContent("“A retro sunset over the peaks.”");
  expect(within(first).getByText("hiking shirt")).toBeVisible();
  expect(within(first).getByText("retro sunset")).toBeVisible();
  const link = within(first).getByRole("link", { name: /Open on Etsy/ });
  expect(link).toHaveAttribute("href", "https://www.etsy.com/listing/1");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noreferrer");

  await user.click(row(2));

  expect(row(1)).toHaveAttribute("aria-expanded", "false");
  expect(row(2)).toHaveAttribute("aria-expanded", "true");
  expect(screen.getAllByRole("link", { name: /Open on Etsy/ })).toHaveLength(1);

  await user.click(row(2));

  expect(screen.queryByRole("link", { name: /Open on Etsy/ })).toBeNull();
});

it("leaves out a lead or tags the listing does not have", async () => {
  const user = userEvent.setup();
  ready(marketSnapshot({ scored: 1, edit: { 1: { lead: "", tags: [] } } }));

  await user.click(row(1));

  const detail = must(
    row(1).closest("li")?.querySelector<HTMLElement>(".mkt-row__detail"),
    "row detail",
  );
  expect(detail.querySelector(".mkt-row__lead")).toBeNull();
  expect(detail.querySelector(".mkt-row__tags")).toBeNull();
  expect(within(detail).getByRole("link")).toBeVisible();
});

it("reveals the rest of the scored listings for good", async () => {
  const user = userEvent.setup();
  ready();
  expect(screen.queryByText("Shirt 9", { exact: false })).toBeNull();

  await user.click(screen.getByRole("button", { name: "Show 4 more scored listings" }));

  expect(screen.queryByRole("button", { name: /more scored listings/ })).toBeNull();
  expect(panel()).toHaveTextContent("Also scored");
  const rest = must(within(panel()).getAllByRole("list")[1], "second list");
  expect(within(rest).getAllByRole("listitem")).toHaveLength(4);
  expect(rest).toHaveTextContent("Retro Sunset Hiking Shirt 9");
});

it("offers no more when every scored listing is an example", () => {
  ready(marketSnapshot({ scored: 8 }));

  expect(screen.queryByRole("button", { name: /more scored listings/ })).toBeNull();
});

it("marks the seller's own listings", () => {
  ready(marketSnapshot({ scored: 2, edit: { 2: { own_shop: true } } }));

  expect(within(row(2)).getByText("Your shop")).toBeVisible();
  expect(row(2)).not.toHaveTextContent("TrailTees2");
  expect(within(row(1)).queryByText("Your shop")).toBeNull();
});

it("leaves out a metric Etsy did not give", () => {
  ready(
    marketSnapshot({
      scored: 1,
      edit: {
        1: { shop_rating: null, favourites_per_day: null, views_per_day: 3.25, reviews: 1284 },
      },
    }),
  );

  expect(within(row(1)).queryByTitle("Favourites per day")).toBeNull();
  expect(within(row(1)).getByTitle("Views per day")).toHaveTextContent("3.3/d");
  expect(within(row(1)).getByTitle("Reviews on this listing")).toHaveTextContent("1.3k");
  expect(row(1).querySelector(".mkt-star")).toBeNull();
});

const suggestions = {
  titles: ["Take A Hike Tee", "Retro Hiking Shirt For Trail Days", "Sunset Peaks Tee"],
  tags: ["hiker gift", "camping tee"],
  description_leads: ["A mountain sunset in faded stripes.", "Lead B", "Lead C"],
};

async function phrases(proposal: typeof suggestions | null) {
  const user = userEvent.setup();
  render(
    <MarketListingsPanel
      state={{ kind: "ready", snapshot: marketSnapshot() }}
      proposal={proposal}
    />,
  );
  await user.click(screen.getByRole("tab", { name: "Phrases" }));
  return within(panel()).getAllByRole("listitem");
}

it("switches between the listings and the phrases they share", async () => {
  const user = userEvent.setup();
  ready();
  const switcher = within(panel()).getByRole("tablist", { name: "Market view" });
  expect(within(switcher).getByRole("tab", { name: "Listings" })).toHaveAttribute(
    "aria-selected",
    "true",
  );

  await user.click(within(switcher).getByRole("tab", { name: "Phrases" }));

  expect(within(switcher).getByRole("tab", { name: "Phrases" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(panel()).toHaveTextContent("Tags the top listings share, strongest first");
  expect(screen.queryByText("Examples shown to AI Mode")).toBeNull();
  const items = within(panel()).getAllByRole("listitem");
  expect(items.map((li) => li.textContent)).toEqual([
    "retro hiking shirt12 listings",
    "Hiker Gift9 listings",
    "mountain sunset4 listings",
  ]);
  const bar = must(items[2]?.querySelector<HTMLElement>(".mkt-score__bar > span"), "bar");
  expect(bar.style.width).toBe("40%");

  await user.click(within(switcher).getByRole("tab", { name: "Listings" }));

  expect(panel()).toHaveTextContent("Examples shown to AI Mode");
});

it("ticks a phrase that is a suggested tag, or is in a suggested title or lead, in any case", async () => {
  const [inTitle, asTag, inLead] = (await phrases(suggestions)).map((li) => within(li));

  expect(inTitle?.getByLabelText("In your suggestions")).toBeInTheDocument();
  expect(asTag?.getByLabelText("In your suggestions")).toBeInTheDocument();
  expect(inLead?.getByLabelText("In your suggestions")).toBeInTheDocument();
  expect(panel()).toHaveTextContent("Ticked phrases made it into the current suggestions.");
});

it("does not tick a phrase the suggestions do not use", async () => {
  const asTag = must((await phrases({ ...suggestions, tags: ["hiker gifts"] }))[1], "phrase");

  expect(within(asTag).queryByLabelText("In your suggestions")).toBeNull();
});

it("has no ticks and no footnote without pending suggestions", async () => {
  const items = await phrases(null);

  for (const item of items) {
    expect(within(item).queryByLabelText("In your suggestions")).toBeNull();
  }
  expect(panel()).not.toHaveTextContent("Ticked phrases");
});

it("shows what it is searching for while the search runs", () => {
  render(
    <MarketListingsPanel state={{ kind: "loading", queries: MARKET_QUERIES }} proposal={null} />,
  );

  const sentence = must(panel().querySelector(".mkt-queries"), "searches line");
  expect(sentence).toHaveClass("mkt-queries--searching");
  expect(sentence).toHaveTextContent(
    "Searching Etsy for “retro sunset hiking shirt”, “take a hike t shirt” and “vintage mountain graphic tee”",
  );
  expect(panel().querySelectorAll(".mkt-row--skeleton")).toHaveLength(5);
  expect(screen.queryByRole("tablist")).toBeNull();
  expect(panel().querySelector(".mkt-head__meta")).toBeNull();
});

it("says the searches are being chosen before there are any", () => {
  render(<MarketListingsPanel state={{ kind: "loading", queries: null }} proposal={null} />);

  expect(panel().querySelector(".mkt-queries")).toHaveTextContent(
    "Choosing Etsy searches from the brief…",
  );
  expect(panel().querySelectorAll(".mkt-row--skeleton")).toHaveLength(5);
});

it("says so when nothing comparable was found", () => {
  render(
    <MarketListingsPanel state={{ kind: "empty", queries: MARKET_QUERIES }} proposal={null} />,
  );

  expect(panel()).toHaveTextContent("Searched Etsy for “retro sunset hiking shirt”");
  expect(panel().querySelector(".mkt-note")).toHaveTextContent(
    "No comparable listings found" +
      "Etsy returned nothing for these searches, even without the age filter. " +
      "The suggestions were written from the design and brief alone.",
  );
  expect(screen.queryByRole("tablist")).toBeNull();
});

it("says why the search failed and that nothing changed", () => {
  render(
    <MarketListingsPanel
      state={{ kind: "failed", reason: "Etsy did not respond (HTTP 503) after 3 retries." }}
      proposal={null}
    />,
  );

  const note = must(panel().querySelector<HTMLElement>(".mkt-note--failed"), "failure note");
  expect(within(note).getByText("Etsy market search failed")).toBeVisible();
  expect(note).toHaveTextContent(
    "Etsy did not respond (HTTP 503) after 3 retries. Nothing changed. Run AI Mode again to retry.",
  );
  expect(panel().querySelector(".mkt-queries")).toBeNull();
});

it("ends a reason that has no full stop with one", () => {
  render(
    <MarketListingsPanel
      state={{ kind: "failed", reason: "no Etsy API key is configured; run `etsy-listings setup`" }}
      proposal={null}
    />,
  );

  expect(panel()).toHaveTextContent(
    "no Etsy API key is configured; run `etsy-listings setup`. Nothing changed.",
  );
});

it("counts one listing as one", async () => {
  const user = userEvent.setup();
  ready(
    marketSnapshot({
      scored: 9,
      phrases: [{ phrase: "yaml error", listings: 1, score: 0.05 }],
    }),
  );

  expect(screen.getByRole("button", { name: "Show 1 more scored listing" })).toBeVisible();
  await user.click(screen.getByRole("tab", { name: "Phrases" }));
  expect(within(panel()).getByRole("listitem")).toHaveTextContent("yaml error1 listing");
});
