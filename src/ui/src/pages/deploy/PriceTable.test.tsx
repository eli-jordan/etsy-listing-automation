import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PriceTable } from "./PriceTable";
import type { PriceRow } from "./comparison";

describe("PriceTable", () => {
  it("renders nothing when there are no price rows", () => {
    const { container } = render(<PriceTable rows={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows before, after and the difference for a raised price", () => {
    const rows: PriceRow[] = [
      { size: "S", before: "349 NOK", after: "379 NOK", changed: true, belowCost: false },
    ];
    render(<PriceTable rows={rows} />);

    expect(screen.getByText("S")).toBeInTheDocument();
    expect(screen.getByText("349 NOK")).toBeInTheDocument();
    expect(screen.getByText("379 NOK")).toBeInTheDocument();
    expect(screen.getByText("+30 NOK")).toBeInTheDocument();
  });

  it("marks a below-cost row and does not invent its own reason for it", () => {
    const rows: PriceRow[] = [
      { size: "XXXL", before: "199 NOK", after: "159 NOK", changed: true, belowCost: true },
    ];
    render(<PriceTable rows={rows} />);

    expect(
      screen.getByText((_, node) => node?.textContent === "159 NOK · below cost"),
    ).toBeInTheDocument();
  });
});
