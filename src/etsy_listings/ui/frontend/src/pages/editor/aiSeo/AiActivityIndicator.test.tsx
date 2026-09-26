import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { WorkflowStep } from "../../../types";
import { AiActivityIndicator } from "./AiActivityIndicator";

/** The page head's one line while an AI run works. Its whole job is telling
 * a seller who is looking at Variants which stage of the chain is running,
 * so every test here is "which message, from which step, and is it
 * announced politely". The three-node indicator that replaces it is PR 7's. */

function steps(
  brief: WorkflowStep["state"],
  market: WorkflowStep["state"],
  seo: WorkflowStep["state"],
): WorkflowStep[] {
  return [
    { id: "brief", state: brief },
    { id: "market", state: market },
    { id: "seo", state: seo },
  ];
}

it("says nothing at all when there is no run", () => {
  const { container } = render(<AiActivityIndicator steps={[]} />);

  expect(container).toBeEmptyDOMElement();
});

it("reports the brief being drafted", () => {
  render(<AiActivityIndicator steps={steps("active", "pending", "pending")} />);

  expect(screen.getByRole("status")).toHaveTextContent("Drafting brief…");
});

it("reports market research, whether or not the brief was drafted", () => {
  render(<AiActivityIndicator steps={steps("skipped", "active", "pending")} />);

  expect(screen.getByRole("status")).toHaveTextContent("Researching the market…");
});

it("reports the suggestions being written", () => {
  render(<AiActivityIndicator steps={steps("done", "warning", "active")} />);

  expect(screen.getByRole("status")).toHaveTextContent("Writing suggestions…");
});

it("says nothing once no step is running", () => {
  const { container } = render(<AiActivityIndicator steps={steps("done", "failed", "pending")} />);

  expect(container).toBeEmptyDOMElement();
});

it("announces politely, once", () => {
  render(<AiActivityIndicator steps={steps("active", "pending", "pending")} />);

  expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
  expect(screen.getAllByRole("status")).toHaveLength(1);
});
