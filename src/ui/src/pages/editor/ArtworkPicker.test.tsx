import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { onPhone } from "../../test/touch";
import { ArtworkPicker } from "./ArtworkPicker";

afterEach(() => vi.unstubAllGlobals());

function renderPicker() {
  render(
    <ArtworkPicker
      title="Designs for light shirts"
      hint="Prints on Ivory"
      cloth="#fff"
      current={null}
      library={[{ name: "take-a-hike", file: "designs/take-a-hike.png" }]}
      onPick={() => undefined}
      onClose={() => undefined}
    />,
  );
  return screen.getByPlaceholderText("Search your designs…");
}

describe("ArtworkPicker's search field", () => {
  it("takes the focus on a desktop, so typing searches at once", () => {
    expect(renderPicker()).toHaveFocus();
  });

  it("leaves the focus alone on a phone, whose keyboard would cover the list", () => {
    onPhone();
    expect(renderPicker()).not.toHaveFocus();
  });
});
