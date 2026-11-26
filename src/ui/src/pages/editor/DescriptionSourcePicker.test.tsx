import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { onPhone } from "../../test/touch";
import { DescriptionSourcePicker } from "./DescriptionSourcePicker";

const scrollIntoView = vi.fn();

beforeEach(() => {
  scrollIntoView.mockClear();
  Element.prototype.scrollIntoView = scrollIntoView;
});

afterEach(() => vi.unstubAllGlobals());

function openMenu() {
  render(
    <DescriptionSourcePicker
      value={null}
      items={[{ ref: "common/care.md", title: "Care", summary: null }]}
      onSelect={() => undefined}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Write inline body" }));
}

describe("DescriptionSourcePicker's menu", () => {
  it("is scrolled into view on a phone, where the field may sit low on the screen", () => {
    onPhone();
    openMenu();
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
  });

  it("is left where it opens on a desktop", () => {
    openMenu();
    expect(scrollIntoView).not.toHaveBeenCalled();
  });
});
