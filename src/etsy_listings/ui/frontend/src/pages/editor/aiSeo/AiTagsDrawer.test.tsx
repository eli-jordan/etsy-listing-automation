import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AiTagsDrawer } from "./AiTagsDrawer";

const tags = Array.from({ length: 20 }, (_, i) => `tag-${i}`);

describe("AiTagsDrawer", () => {
  it("labels the drawer and splits Best 13 from More options", () => {
    render(
      <AiTagsDrawer
        tags={tags}
        selected={[]}
        staleReason={null}
        rationale={[]}
        warnings={[]}
        observedText=""
        onToggle={vi.fn()}
        onAcceptBest={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByRole("region", { name: "tag AI suggestions" })).toBeInTheDocument();
    expect(screen.getByText("Best 13")).toBeInTheDocument();
    expect(screen.getByText("More options")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /tag-0$/ })).toBeInTheDocument();
  });

  it("shows the current count out of 13", () => {
    render(
      <AiTagsDrawer
        tags={tags}
        selected={["tag-0", "tag-1"]}
        staleReason={null}
        rationale={[]}
        warnings={[]}
        observedText=""
        onToggle={vi.fn()}
        onAcceptBest={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText("2 of 13 tags selected")).toBeInTheDocument();
  });

  it("exposes aria-pressed for each tag's selected state", () => {
    render(
      <AiTagsDrawer
        tags={tags}
        selected={["tag-0"]}
        staleReason={null}
        rationale={[]}
        warnings={[]}
        observedText=""
        onToggle={vi.fn()}
        onAcceptBest={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /tag-0$/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /tag-1$/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("calls onToggle for an activated tag", async () => {
    const onToggle = vi.fn();
    render(
      <AiTagsDrawer
        tags={tags}
        selected={[]}
        staleReason={null}
        rationale={[]}
        warnings={[]}
        observedText=""
        onToggle={onToggle}
        onAcceptBest={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /tag-0/ }));
    expect(onToggle).toHaveBeenCalledWith("tag-0");
  });

  it("disables every unselected tag once 13 are selected, but keeps selected ones enabled", () => {
    const thirteen = tags.slice(0, 13);
    render(
      <AiTagsDrawer
        tags={tags}
        selected={thirteen}
        staleReason={null}
        rationale={[]}
        warnings={[]}
        observedText=""
        onToggle={vi.fn()}
        onAcceptBest={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /tag-0/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /tag-13/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /tag-13/ })).toHaveAttribute("aria-disabled", "true");
  });

  it("calls onAcceptBest", () => {
    const onAcceptBest = vi.fn();
    render(
      <AiTagsDrawer
        tags={tags}
        selected={[]}
        staleReason={null}
        rationale={[]}
        warnings={[]}
        observedText=""
        onToggle={vi.fn()}
        onAcceptBest={onAcceptBest}
        onClose={vi.fn()}
      />,
    );
    screen.getByRole("button", { name: /accept best 13/i }).click();
    expect(onAcceptBest).toHaveBeenCalled();
  });

  it("keeps an out-of-date drawer's tags and Accept best 13 usable, with the reason as its heading", async () => {
    const onToggle = vi.fn();
    const onAcceptBest = vi.fn();
    render(
      <AiTagsDrawer
        tags={tags}
        selected={[]}
        staleReason="colours changed since"
        rationale={[]}
        warnings={[]}
        observedText=""
        onToggle={onToggle}
        onAcceptBest={onAcceptBest}
        onClose={vi.fn()}
      />,
    );

    expect(
      screen.getByText("Out of date: colours changed since. Still usable"),
    ).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "tag AI suggestions" })).toHaveClass(
      "seo-suggestion--stale",
    );
    await userEvent.click(screen.getByRole("button", { name: /tag-0/ }));
    await userEvent.click(screen.getByRole("button", { name: /accept best 13/i }));
    expect(onToggle).toHaveBeenCalledWith("tag-0");
    expect(onAcceptBest).toHaveBeenCalled();
  });

  it("calls onClose when Close is activated", async () => {
    const onClose = vi.fn();
    render(
      <AiTagsDrawer
        tags={tags}
        selected={[]}
        staleReason={null}
        rationale={[]}
        warnings={[]}
        observedText=""
        onToggle={vi.fn()}
        onAcceptBest={vi.fn()}
        onClose={onClose}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("filters rationale to tag entries in its disclosure", () => {
    render(
      <AiTagsDrawer
        tags={tags}
        selected={[]}
        staleReason={null}
        rationale={[
          {
            phrase: "gift for hikers",
            intent: "bottom_of_funnel",
            reason: "gift intent",
            used_in: ["tags"],
          },
          {
            phrase: "take a hike",
            intent: "core_product",
            reason: "title only",
            used_in: ["title"],
          },
        ]}
        warnings={[]}
        observedText=""
        onToggle={vi.fn()}
        onAcceptBest={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText(/gift intent/)).toBeInTheDocument();
    expect(screen.queryByText(/title only/)).not.toBeInTheDocument();
  });

  it("has a ref-able first tag choice for focus management", () => {
    render(
      <AiTagsDrawer
        tags={tags}
        selected={[]}
        staleReason={null}
        rationale={[]}
        warnings={[]}
        observedText=""
        onToggle={vi.fn()}
        onAcceptBest={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    const region = screen.getByRole("region", { name: "tag AI suggestions" });
    const pools = within(region).getAllByRole("button", { name: /tag-0\b/ });
    expect(pools).toHaveLength(1);
    expect(region.querySelector(".seo-tag-pool button")).toBe(pools[0]);
  });
});
