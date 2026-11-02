import { expect, it } from "vitest";
import { listingDetail } from "../../test/listings";
import type { ListingDetail } from "../../types";
import { listingDocument } from "./listingDocument";

it("keeps template positions in editor saves", () => {
  const positions: ListingDetail["template_positions"] = {
    flat: {
      bounding_box: [
        { x: 10, y: 20 },
        { x: 110, y: 20 },
        { x: 110, y: 220 },
        { x: 10, y: 220 },
      ],
    },
  };
  expect(
    listingDocument(listingDetail({ template_positions: positions })).template_positions,
  ).toEqual(positions);
});

it("carries a cleared position so the server can remove it", () => {
  expect(listingDocument(listingDetail({ template_positions: null }))).toHaveProperty(
    "template_positions",
    null,
  );
});
