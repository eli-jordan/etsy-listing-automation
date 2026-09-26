import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WorkflowStep } from "../../../types";
import { AiWorkflowIndicator } from "./AiWorkflowIndicator";

/** The page head's three nodes (docs/ui-market-seo-interactions.md,
 * section 1). What a seller reads from it: which stage is running, which one
 * was skipped, warned or failed, and -- on hover or focus -- what each stage
 * does and what it did this run. */

type State = WorkflowStep["state"];

function steps(
  brief: State,
  market: State,
  seo: State,
  details: Partial<Record<WorkflowStep["id"], string>> = {},
): WorkflowStep[] {
  return [
    { id: "brief", state: brief, detail: details.brief ?? null },
    { id: "market", state: market, detail: details.market ?? null },
    { id: "seo", state: seo, detail: details.seo ?? null },
  ];
}

it("names the running stage in one line and in each node", () => {
  render(<AiWorkflowIndicator steps={steps("active", "pending", "pending")} running />);

  const status = screen.getByRole("status", { name: "AI Mode: Drafting brief…" });
  expect(status).toHaveAttribute("aria-live", "polite");
  expect(status).toHaveTextContent("Drafting brief…");
  expect(screen.getByLabelText("Brief: In progress")).toBeInTheDocument();
  expect(screen.getByLabelText("Market research: Waiting")).toBeInTheDocument();
  expect(screen.getByLabelText("SEO suggestions: Waiting")).toBeInTheDocument();
});

it("says nothing when there is no run", () => {
  const { container } = render(<AiWorkflowIndicator steps={[]} running={false} />);

  expect(container).toBeEmptyDOMElement();
});

it("shows a skipped brief greyed with a skip badge, and says why on hover", () => {
  const { container } = render(
    <AiWorkflowIndicator
      steps={steps("skipped", "active", "pending", {
        brief: "You wrote the brief, so it was kept",
        market: "Searching Etsy for 3 phrases…",
      })}
      running
    />,
  );

  expect(
    screen.getByRole("status", { name: "AI Mode: Researching the market…" }),
  ).toBeInTheDocument();
  const brief = screen.getByLabelText("Brief: Skipped");
  expect(brief).toHaveClass("aiflow__node--skipped");
  expect(brief.querySelector(".aiflow__badge--skipped")).not.toBeNull();
  expect(brief).toHaveAccessibleDescription(
    /^Brief\s*Skipped\s*Describes the design .* only when the Brief field is empty\.\s*You wrote the brief, so it was kept$/,
  );
  // The chain moved past the skipped node, so the connector out of it is solid.
  const links = container.querySelectorAll(".aiflow__link");
  expect(links).toHaveLength(2);
  expect(links[0]).toHaveClass("aiflow__link--done");
  expect(links[1]).not.toHaveClass("aiflow__link--done");
});

it("describes each node's stage, and this run's detail only when there is one", () => {
  render(
    <AiWorkflowIndicator
      steps={steps("done", "done", "active", {
        brief: "Drafted from take-a-hike.png",
        market: "20 listings scored, from 58 found",
      })}
      running
    />,
  );

  expect(screen.getByRole("status", { name: "AI Mode: Writing suggestions…" })).toBeInTheDocument();
  expect(screen.getByLabelText("Market research: Done")).toHaveAccessibleDescription(
    /^Market research\s*Done\s*Turns the brief into three Etsy searches, .*\s*20 listings scored, from 58 found$/,
  );
  const seo = screen.getByLabelText("SEO suggestions: In progress");
  expect(seo).toHaveAccessibleDescription(
    /^SEO suggestions\s*In progress\s*Writes title, tag and .* use\.$/,
  );
  expect(seo.querySelector(".aiflow__tip-detail")).toBeNull();
  // Done has no badge: the tint and the solid connector already say it.
  expect(screen.getByLabelText("Brief: Done").querySelector(".aiflow__badge")).toBeNull();
  for (const node of [screen.getByLabelText("Brief: Done"), seo]) {
    expect(node).toHaveAttribute("tabindex", "0");
  }
});

it("carries on past a market warning with an amber badge", () => {
  render(
    <AiWorkflowIndicator
      steps={steps("done", "warning", "active", {
        market: "No comparable listings found, even with filters relaxed",
      })}
      running
    />,
  );

  expect(screen.getByRole("status", { name: "AI Mode: Writing suggestions…" })).toBeInTheDocument();
  const market = screen.getByLabelText("Market research: Done, with a warning");
  expect(market.querySelector(".aiflow__badge--warning")).not.toBeNull();
  expect(market).toHaveAccessibleDescription(
    /No comparable listings found, even with filters relaxed$/,
  );
});

it("stops at a failed node, in red, and says which stage failed", () => {
  const { container } = render(
    <AiWorkflowIndicator
      steps={steps("done", "failed", "pending", {
        market: "Etsy market search failed: Etsy did not respond (HTTP 503) after 3 retries",
        seo: "Not started",
      })}
      running={false}
    />,
  );

  expect(
    screen.getByRole("status", { name: "AI Mode: Market research failed" }),
  ).toBeInTheDocument();
  expect(container.querySelector(".aiflow__label")).toHaveClass("aiflow__label--failed");
  const market = screen.getByLabelText("Market research: Failed");
  expect(market.querySelector(".aiflow__badge--failed")).not.toBeNull();
  expect(market).toHaveAccessibleDescription(
    /Etsy market search failed: Etsy did not respond \(HTTP 503\) after 3 retries$/,
  );
  expect(screen.getByLabelText("SEO suggestions: Waiting")).toHaveAccessibleDescription(
    /Not started$/,
  );
});

it("says nothing about a run that was cancelled", () => {
  /* Cancel leaves every node pending ("Cancelled", "Not started"): the
     seller stopped it, and there is nothing left to report. */
  const { container } = render(
    <AiWorkflowIndicator steps={steps("skipped", "pending", "pending")} running={false} />,
  );

  expect(container).toBeEmptyDOMElement();
});

describe("once every step is done or skipped", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  /** A run this editor watched: running, then finished. */
  function finish(final: WorkflowStep[]) {
    const view = render(<AiWorkflowIndicator steps={steps("done", "done", "active")} running />);
    view.rerender(<AiWorkflowIndicator steps={final} running={false} />);
    return view;
  }

  it("says the suggestions are ready for 4 seconds, fades out over 300ms, then says nothing", () => {
    const { container } = finish(steps("skipped", "done", "done"));
    const status = screen.getByRole("status", { name: "AI Mode: Suggestions ready" });
    expect(container.querySelector(".aiflow__label")).toHaveClass("aiflow__label--done");

    act(() => vi.advanceTimersByTime(3999));
    expect(status).not.toHaveClass("aiflow--fading");

    act(() => vi.advanceTimersByTime(1));
    expect(status).toHaveClass("aiflow--fading");

    act(() => vi.advanceTimersByTime(299));
    expect(container).not.toBeEmptyDOMElement();

    act(() => vi.advanceTimersByTime(1));
    expect(container).toBeEmptyDOMElement();
  });

  it("hides at once, with no fade, for a seller who asked for less motion", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
    }));
    const { container } = finish(steps("done", "done", "done"));

    act(() => vi.advanceTimersByTime(3999));
    expect(screen.getByRole("status")).not.toHaveClass("aiflow--fading");

    act(() => vi.advanceTimersByTime(1));
    expect(container).toBeEmptyDOMElement();
  });

  it("keeps a warning, since it needs a second look", () => {
    finish(steps("done", "warning", "done"));

    act(() => vi.advanceTimersByTime(60_000));
    const status = screen.getByRole("status", { name: "AI Mode: Suggestions ready" });
    expect(status).not.toHaveClass("aiflow--fading");
  });

  it("keeps a failure", () => {
    finish(steps("done", "failed", "pending"));

    act(() => vi.advanceTimersByTime(60_000));
    expect(
      screen.getByRole("status", { name: "AI Mode: Market research failed" }),
    ).toBeInTheDocument();
  });

  it("shows the next run again after the last one faded", () => {
    const view = finish(steps("done", "done", "done"));
    act(() => vi.advanceTimersByTime(4300));
    expect(view.container).toBeEmptyDOMElement();

    // Starting a run clears the steps, then its first events arrive.
    view.rerender(<AiWorkflowIndicator steps={[]} running />);
    view.rerender(<AiWorkflowIndicator steps={steps("skipped", "active", "pending")} running />);

    expect(
      screen.getByRole("status", { name: "AI Mode: Researching the market…" }),
    ).toBeInTheDocument();
  });

  it("says nothing about a run that had already finished when the editor found it", () => {
    /* A reattach to a finished run (a return to the editor, a reload) is
       not news: the seller either saw it finish or wasn't here. So it comes
       back as it was left -- faded -- rather than flashing "ready" on every
       visit. A warning or a failure still shows; see the tests above. */
    const { container } = render(
      <AiWorkflowIndicator steps={steps("done", "done", "done")} running={false} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
