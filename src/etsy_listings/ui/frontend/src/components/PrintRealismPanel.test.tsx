import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DisplaceConfig, ShadeConfig } from "../types";
import { PrintRealismPanel } from "./PrintRealismPanel";

/** Wireframe 2a renames the render passes after what they do to a photograph.
 * The mapping is the whole point of this component, so most of what is tested
 * here is that the plain-language control still writes the right config. */

const DISPLACE: DisplaceConfig = { enabled: true, strength: 0.45 };
const SHADE: ShadeConfig = { enabled: true, opacity: 0.62, blend: "soft-light" };

function renderPanel(over: Partial<Parameters<typeof PrintRealismPanel>[0]> = {}) {
  const onDisplaceChange = vi.fn();
  const onShadeChange = vi.fn();
  render(
    <PrintRealismPanel
      displace={DISPLACE}
      shade={SHADE}
      onDisplaceChange={onDisplaceChange}
      onShadeChange={onShadeChange}
      {...over}
    />,
  );
  return { onDisplaceChange, onShadeChange };
}

describe("PrintRealismPanel", () => {
  it("names the passes after what they do, not after the pass", () => {
    renderPanel();
    expect(screen.getByText("Follow fabric wrinkles")).toBeInTheDocument();
    expect(screen.getByText("Pick up garment shading")).toBeInTheDocument();
    expect(screen.queryByText("Displace")).not.toBeInTheDocument();
    expect(screen.queryByText("Shade")).not.toBeInTheDocument();
  });

  it("shows each strength as a percentage", () => {
    renderPanel();
    expect(screen.getByText("45%")).toBeInTheDocument();
    expect(screen.getByText("62%")).toBeInTheDocument();
  });

  it("turns the wrinkle pass on and off", () => {
    const { onDisplaceChange } = renderPanel({ displace: { enabled: false, strength: 0.45 } });
    fireEvent.click(screen.getByLabelText("Follow fabric wrinkles"));
    expect(onDisplaceChange).toHaveBeenCalledWith({ enabled: true, strength: 0.45 });
  });

  it("writes the slider back as a 0..1 fraction, not a percentage", () => {
    const { onDisplaceChange } = renderPanel();
    fireEvent.change(screen.getByLabelText("Wrinkle strength"), { target: { value: "80" } });
    expect(onDisplaceChange).toHaveBeenCalledWith({ enabled: true, strength: 0.8 });
  });

  it("writes the shading slider back as a fraction too", () => {
    const { onShadeChange } = renderPanel();
    fireEvent.change(screen.getByLabelText("Shading strength"), { target: { value: "20" } });
    expect(onShadeChange).toHaveBeenCalledWith({ ...SHADE, opacity: 0.2 });
  });

  describe("shading style presets", () => {
    it("maps Natural to the soft-light blend", () => {
      const { onShadeChange } = renderPanel({ shade: { ...SHADE, blend: "multiply" } });
      fireEvent.click(screen.getByRole("button", { name: "Natural" }));
      expect(onShadeChange).toHaveBeenCalledWith({ ...SHADE, blend: "soft-light" });
    });

    it("maps Rich to multiply", () => {
      const { onShadeChange } = renderPanel();
      fireEvent.click(screen.getByRole("button", { name: "Rich" }));
      expect(onShadeChange).toHaveBeenCalledWith({ ...SHADE, blend: "multiply" });
    });

    it("maps Airy to the grey pivot", () => {
      const { onShadeChange } = renderPanel();
      fireEvent.click(screen.getByRole("button", { name: "Airy" }));
      expect(onShadeChange).toHaveBeenCalledWith({ ...SHADE, blend: "grey-pivot" });
    });

    it("marks the preset matching the current blend", () => {
      renderPanel({ shade: { ...SHADE, blend: "multiply" } });
      expect(screen.getByRole("button", { name: "Rich" })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByRole("button", { name: "Natural" })).toHaveAttribute(
        "aria-pressed",
        "false",
      );
    });
  });

  it("keeps the raw values reachable, since the config and the goldens use them", () => {
    renderPanel();
    // The pass names are what template.yaml, every golden and every error
    // message use -- renaming them in the UI must not make them unfindable.
    const advanced = screen.getByText(/Advanced/);
    fireEvent.click(advanced);
    expect(screen.getByText(/displace\.strength/)).toBeInTheDocument();
    expect(screen.getByText(/soft-light/)).toBeInTheDocument();
  });

  it("resets both passes to their defaults", () => {
    const { onDisplaceChange, onShadeChange } = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Reset print realism" }));
    expect(onDisplaceChange).toHaveBeenCalledWith({ enabled: false, strength: 0 });
    expect(onShadeChange).toHaveBeenCalledWith({
      enabled: true,
      opacity: 0.6,
      blend: "soft-light",
    });
  });

  it("dims a pass's controls when the pass is off", () => {
    renderPanel({ displace: { enabled: false, strength: 0.45 } });
    expect(screen.getByLabelText("Wrinkle strength")).toBeDisabled();
    expect(screen.getByLabelText("Shading strength")).toBeEnabled();
  });
});
