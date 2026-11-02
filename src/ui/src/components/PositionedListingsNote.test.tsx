import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../api/calibrator";
import { deferred } from "../test/helpers";
import { PositionedListingsNote } from "./PositionedListingsNote";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PositionedListingsNote", () => {
  it("shows nothing when the read fails", async () => {
    const read = vi
      .spyOn(calibrator, "getPositionedListings")
      .mockRejectedValue(new calibrator.CalibratorApiError("down"));

    render(<PositionedListingsNote templateName="flat-lay-01" savedAt={null} />);

    await waitFor(() => expect(read).toHaveBeenCalled());
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("does not show the previous template's listings under the next one", async () => {
    const next = deferred<calibrator.PositionedListing[]>();
    vi.spyOn(calibrator, "getPositionedListings")
      .mockResolvedValueOnce([{ listing: "take-a-hike", placements: [] }])
      .mockReturnValueOnce(next.promise);

    const { rerender } = render(<PositionedListingsNote templateName="first" savedAt={null} />);
    expect(await screen.findByRole("note")).toHaveTextContent("take-a-hike");

    rerender(<PositionedListingsNote templateName="second" savedAt={null} />);
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    next.resolve([{ listing: "tote-bag", placements: ["front"] }]);
    expect(await screen.findByRole("note")).toHaveTextContent("tote-bag (front)");
  });
});
