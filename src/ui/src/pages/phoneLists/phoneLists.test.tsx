import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import * as listingsApi from "../../api/listings";
import * as runsApi from "../../api/runs";
import { EditableName } from "../../components/EditableName";
import { DashboardPage } from "../DashboardPage";
import { ListingsPage } from "../ListingsPage";
import { resetLoadedListingsForTests } from "../loadedListings";
import { PHONE_QUERY } from "../../phone/usePhone";
import type { ListingSummary } from "../../types";
import { PhoneStatusChips } from "./PhoneListingList";
import { rowActions } from "./rowActions";

/* The phone branches of the lists pages. jsdom has no matchMedia, which
   `useIsPhone` reads as "not a phone"; these tests stub it to match. */

function summary(over: Partial<ListingSummary> & { name: string }): ListingSummary {
  return {
    garment_profile: "comfort-colors-1717",
    design: "take-a-hike",
    colour_count: 2,
    status: "draft",
    issue_counts: { block: 0, warn: 0 },
    gestures: [],
    ...over,
  };
}

function stubPhone(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: matches && query === PHONE_QUERY,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

function EditorStub() {
  const { name } = useParams();
  return <p>editor for {name}</p>;
}

function Address() {
  const { search } = useLocation();
  return <output aria-label="address">{search}</output>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Address />
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/listings" element={<ListingsPage />} />
        <Route path="/listings/new" element={<p>new-listing page</p>} />
        <Route path="/listings/:name" element={<EditorStub />} />
      </Routes>
    </MemoryRouter>,
  );
}

const LIVE = summary({
  name: "live-shirt",
  status: "live",
  etsy_listing_id: 123,
  printify_product_id: "p1",
  gestures: ["retire", "delete"],
});
const MARKED = summary({ name: "marked-shirt", status: "pending-delete", gestures: ["cancel"] });
const LISTINGS = [
  summary({ name: "draft-shirt", status: "draft", gestures: ["delete"] }),
  LIVE,
  MARKED,
];

beforeEach(() => {
  vi.spyOn(runsApi, "currentWorkspaceRun").mockResolvedValue(null);
  vi.spyOn(listingsApi, "listListings").mockResolvedValue(LISTINGS);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  resetLoadedListingsForTests();
});

describe("rowActions", () => {
  it("offers the row's links out, then its gestures in the table's words", () => {
    const onGesture = vi.fn();
    const actions = rowActions(LIVE, onGesture);
    expect(actions.map((a) => a.label)).toEqual([
      "Open in Etsy",
      "Open in Printify",
      "Retire",
      "Mark for deletion",
    ]);
    const [etsy, , retire, remove] = actions;
    expect(etsy?.kind === "link" && etsy.href).toContain("123");
    expect(remove?.kind === "action" && remove.danger).toBe(true);
    if (retire?.kind === "action") retire.onSelect();
    expect(onGesture).toHaveBeenCalledWith(LIVE, "retire");

    expect(rowActions(MARKED, onGesture).map((a) => a.label)).toEqual(["Undo mark for delete"]);
  });
});

describe("PhoneStatusChips", () => {
  it("shows All and only the states some listing is in, with counts", () => {
    const onChange = vi.fn();
    render(<PhoneStatusChips listings={LISTINGS} value="all" onChange={onChange} />);
    const chips = screen.getAllByRole("radio").map((chip) => chip.textContent);
    expect(chips).toEqual(["All3", "Draft1", "Live1", "Pending delete1"]);
    fireEvent.click(screen.getByRole("radio", { name: /^Live/ }));
    expect(onChange).toHaveBeenCalledWith("live");
  });

  it("keeps the chosen state's chip when nothing is in it", () => {
    render(<PhoneStatusChips listings={LISTINGS} value="dirty" onChange={vi.fn()} />);
    expect(screen.getByRole("radio", { name: /^Dirty/ }).getAttribute("aria-checked")).toBe("true");
  });
});

describe("ListingsPage on a phone", () => {
  beforeEach(() => stubPhone(true));

  it("lists rows instead of a table, and a row opens its listing", async () => {
    renderAt("/listings");
    const list = await screen.findByRole("list", { name: "Listings" });
    expect(document.querySelector("table")).toBeNull();
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    fireEvent.click(within(list).getByText("draft-shirt"));
    expect(await screen.findByText("editor for draft-shirt")).toBeTruthy();
  });

  it("puts a row's actions in a sheet, and an action runs the gesture", async () => {
    const patch = vi.spyOn(listingsApi, "patchListing").mockResolvedValue({} as never);
    renderAt("/listings");
    fireEvent.click(await screen.findByRole("button", { name: "More actions for marked-shirt" }));
    const sheet = screen.getByRole("dialog", { name: "marked-shirt" });
    fireEvent.click(within(sheet).getByRole("button", { name: "Undo mark for delete" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(patch).toHaveBeenCalledWith("marked-shirt", { lifecycle: null });
  });

  it("filters with chips, and New listing is the floating button", async () => {
    renderAt("/listings");
    await screen.findByRole("list", { name: "Listings" });
    expect(screen.queryByRole("button", { name: "+ New listing" })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: /^Live/ }));
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "New listing" }));
    expect(await screen.findByText("new-listing page")).toBeTruthy();
  });

  it("keeps both a chip tapped and a search typed before the router has answered", async () => {
    renderAt("/listings");
    await screen.findByRole("list", { name: "Listings" });

    act(() => {
      fireEvent.click(screen.getByRole("radio", { name: /^Live/ }));
      fireEvent.change(screen.getByPlaceholderText("Search listings…"), {
        target: { value: "shirt" },
      });
    });

    expect(screen.getByLabelText("address").textContent).toBe("?status=live&q=shirt");
  });

  it("starts filtered by ?status=, which the Dashboard's counts link to", async () => {
    renderAt("/");
    const live = await screen.findByRole("link", { name: /Live/ });
    expect(live.getAttribute("href")).toBe("/listings?status=live");
    fireEvent.click(live);
    await screen.findByRole("list", { name: "Listings" });
    expect(screen.getByRole("radio", { name: /^Live/ }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });
});

describe("ListingsPage on the desktop", () => {
  it("keeps the table, the select and the head's New listing", async () => {
    renderAt("/listings");
    expect(await screen.findByRole("button", { name: "draft-shirt" })).toBeTruthy();
    expect(document.querySelector("table.listings")).not.toBeNull();
    expect(screen.getByRole("button", { name: "+ New listing" })).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Listings" })).toBeNull();
  });

  it("does not make the Dashboard's counts links", async () => {
    renderAt("/");
    await screen.findByText("not applied yet");
    expect(screen.queryByRole("link")).toBeNull();
  });
});

describe("EditableName on a phone", () => {
  it("opens on a single tap and says so", () => {
    stubPhone(true);
    render(<EditableName value="take-a-hike" onCommit={vi.fn()} />);
    const heading = screen.getByRole("heading");
    expect(heading.getAttribute("title")).toBe("Tap to rename");
    fireEvent.click(heading);
    expect(screen.getByLabelText("Listing name")).toBeTruthy();
  });

  it("still needs a double-click on the desktop", () => {
    render(<EditableName value="take-a-hike" onCommit={vi.fn()} />);
    fireEvent.click(screen.getByRole("heading"));
    expect(screen.queryByLabelText("Listing name")).toBeNull();
  });
});
