import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Lightbox, type LightboxItem } from "./Lightbox";

const ITEMS: LightboxItem[] = [
  { id: "black", label: "black", url: "blob:black" },
  { id: "ivory", label: "ivory", url: "blob:ivory" },
  { id: "moss", label: "moss", url: "blob:moss" },
];

function setup(props: Partial<Parameters<typeof Lightbox>[0]> = {}) {
  const onIndexChange = vi.fn();
  const onClose = vi.fn();
  const onActualSizeChange = vi.fn();
  const view = render(
    <Lightbox
      items={ITEMS}
      index={1}
      actualSize={false}
      onActualSizeChange={onActualSizeChange}
      onIndexChange={onIndexChange}
      onClose={onClose}
      {...props}
    />,
  );
  return { ...view, onIndexChange, onClose, onActualSizeChange };
}

describe("Lightbox", () => {
  it("shows the item at the given index, and where it sits in the set", () => {
    setup();
    expect(screen.getByAltText("ivory")).toHaveAttribute("src", "blob:ivory");
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
  });

  it("arrow keys walk the set and wrap", () => {
    const { onIndexChange } = setup();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(onIndexChange).toHaveBeenLastCalledWith(2);
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(onIndexChange).toHaveBeenLastCalledWith(0);
  });

  it("wraps past the ends rather than stopping", () => {
    const { onIndexChange } = setup({ index: 2 });
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(onIndexChange).toHaveBeenLastCalledWith(0);
  });

  it("does not offer stepping through a set of one", () => {
    const { onIndexChange } = setup({ items: [ITEMS[0] as LightboxItem], index: 0 });
    expect(screen.queryByLabelText("Next preview")).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(onIndexChange).not.toHaveBeenCalled();
  });

  it("closes on Escape and on a click that lands on the backdrop", () => {
    const { onClose, container } = setup();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledTimes(2);

    // A click on the image is not a click on the backdrop -- releasing a drag
    // inside the picture must not shut the thing you are studying.
    fireEvent.click(screen.getByAltText("ivory"));
    expect(onClose).toHaveBeenCalledTimes(2);
    expect(container.querySelector(".lightbox__stage--actual")).toBeNull();
  });

  it("1:1 is a toggle owned above, so it survives stepping between images", () => {
    const { onActualSizeChange } = setup();
    fireEvent.click(screen.getByRole("button", { name: "1:1" }));
    expect(onActualSizeChange).toHaveBeenCalledWith(true);
  });

  it("scrolls at true pixels rather than shrinking to fit", () => {
    const { container } = setup({ actualSize: true });
    expect(container.querySelector(".lightbox__stage--actual")).not.toBeNull();
    expect(screen.getByRole("button", { name: "1:1" })).toHaveAttribute("aria-pressed", "true");
  });

  it("the buttons step the set and close it too", () => {
    const { onIndexChange, onClose } = setup();
    fireEvent.click(screen.getByLabelText("Previous preview"));
    expect(onIndexChange).toHaveBeenLastCalledWith(0);
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("renders nothing for an index that is not in the set", () => {
    const { container } = setup({ index: 9 });
    expect(container.querySelector(".lightbox")).toBeNull();
  });
});
