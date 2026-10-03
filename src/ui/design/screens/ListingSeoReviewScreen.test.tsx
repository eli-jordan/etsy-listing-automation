import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ListingSeoReviewScreen } from "./ListingSeoReviewScreen";

function renderAndRunAiMode() {
  render(<ListingSeoReviewScreen />);
  fireEvent.click(screen.getByRole("button", { name: /ai mode/i }));
  expect(screen.getByRole("status")).toHaveTextContent("Generating title, tag, and description suggestions");
  act(() => vi.advanceTimersByTime(650));
}

describe("ListingSeoReviewScreen prototype", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("reveals suggestions automatically when AI Mode finishes", () => {
    renderAndRunAiMode();

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByLabelText("title AI suggestions")).toBeInTheDocument();
    expect(screen.getByLabelText("tag AI suggestions")).toBeInTheDocument();
    expect(screen.getByLabelText("description lead AI suggestions")).toBeInTheDocument();
  });

  it("applies one title choice and closes its drawer", () => {
    renderAndRunAiMode();

    const drawer = screen.getByLabelText("title AI suggestions");
    fireEvent.click(within(drawer).getByRole("button", { name: /take a hike retro sunset hiking shirt/i }));

    expect(screen.getByLabelText("Title")).toHaveValue("Take A Hike Retro Sunset Hiking Shirt");
    expect(screen.queryByLabelText("title AI suggestions")).not.toBeInTheDocument();
  });

  it("rejects all description-lead choices without changing the field", () => {
    renderAndRunAiMode();

    const drawer = screen.getByLabelText("description lead AI suggestions");
    fireEvent.click(within(drawer).getByRole("button", { name: /reject all/i }));

    expect(screen.getByLabelText("Description lead")).toHaveValue("");
    expect(screen.queryByLabelText("description lead AI suggestions")).not.toBeInTheDocument();
  });

  it("adds individual tags and can replace them with the best thirteen", () => {
    renderAndRunAiMode();

    const drawer = screen.getByLabelText("tag AI suggestions");
    fireEvent.click(within(drawer).getByRole("button", { name: /retro hiking shirt/i }));
    expect(screen.getByRole("button", { name: "Remove retro hiking shirt" })).toBeInTheDocument();
    expect(within(drawer).getByText("1 of 13 tags selected")).toBeInTheDocument();

    fireEvent.click(within(drawer).getByRole("button", { name: /accept best 13/i }));
    expect(screen.getByText("13 / 13")).toBeInTheDocument();
    expect(screen.queryByLabelText("tag AI suggestions")).not.toBeInTheDocument();
  });
});
