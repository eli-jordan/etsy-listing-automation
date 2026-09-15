import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import * as listingsApi from "../api/listings";
import { NewListingPage } from "./NewListingPage";

function EditorStub() {
  const { name } = useParams();
  return <p>editor for {name}</p>;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/listings/new"]}>
      <Routes>
        <Route path="/listings" element={<p>listings page</p>} />
        <Route path="/listings/new" element={<NewListingPage />} />
        <Route path="/listings/:name" element={<EditorStub />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("NewListingPage", () => {
  it("creates a listing with the picked design/garment profile and navigates to its editor", async () => {
    vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue([
      { name: "take-a-hike", file: "designs/take-a-hike.png" },
    ]);
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      { name: "comfort-colors-1717", sizes: ["S", "M"], colors: { black: "dark", white: "light" } },
    ]);
    const createSpy = vi.spyOn(listingsApi, "createListing").mockResolvedValue({
      name: "my-new-shirt",
    } as never);

    renderPage();
    fireEvent.change(await screen.findByLabelText("Name"), {
      target: { value: "my-new-shirt" },
    });
    await waitFor(() => expect(screen.getByLabelText("Design")).toHaveValue("take-a-hike"));

    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(createSpy).toHaveBeenCalledWith({
        name: "my-new-shirt",
        design: "take-a-hike",
        garment_profile: "comfort-colors-1717",
        colors: ["black", "white"],
      }),
    );
    await waitFor(() => expect(screen.getByText("editor for my-new-shirt")).toBeInTheDocument());
  });

  it("disables Create until a name is entered", async () => {
    vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue([
      { name: "take-a-hike", file: "designs/take-a-hike.png" },
    ]);
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      { name: "comfort-colors-1717", sizes: ["S"], colors: {} },
    ]);
    renderPage();
    await screen.findByLabelText("Name");
    expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
  });

  it("reports a status message when creation fails", async () => {
    vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue([
      { name: "take-a-hike", file: "designs/take-a-hike.png" },
    ]);
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      { name: "comfort-colors-1717", sizes: ["S"], colors: {} },
    ]);
    vi.spyOn(listingsApi, "createListing").mockRejectedValue(new Error("no pricing plan"));

    renderPage();
    fireEvent.change(await screen.findByLabelText("Name"), {
      target: { value: "my-new-shirt" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(screen.getByText("could not create listing")).toBeInTheDocument());
  });

  it("cancel returns to the listings page", async () => {
    vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue([]);
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([]);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByText("listings page")).toBeInTheDocument());
  });
});
