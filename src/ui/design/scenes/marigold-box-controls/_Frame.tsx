import { useState } from "react";
import { EyeIcon } from "@phosphor-icons/react/dist/csr/Eye";
import { BoundingBoxIcon } from "@phosphor-icons/react/dist/csr/BoundingBox";
import { SlidersHorizontalIcon } from "@phosphor-icons/react/dist/csr/SlidersHorizontal";
import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { MarigoldScreen } from "./_MarigoldScreen";
import { MaskToolbar } from "./_MaskToolbar";
import "./_box-controls.css";
type Variant = "switch" | "modes" | "chip" | "strip" | "menu";
export function BoxControlFrame({ variant }: { variant: Variant }) {
  const [shown, setShown] = useState(true);
  const [open, setOpen] = useState(variant === "menu");
  const toggle = () => setShown(!shown);
  const switchButton = (
    <button
      className="bv-switch"
      role="switch"
      aria-label="Show design box"
      aria-checked={shown}
      onClick={toggle}
    >
      <i />
    </button>
  );
  const control =
    variant === "switch" ? (
      <div className="bv-switch-control">
        <BoundingBoxIcon />
        <span>Design box</span>
        {switchButton}
      </div>
    ) : variant === "modes" ? (
      <div className="bv-modes" role="group" aria-label="Design box view">
        <button aria-pressed={shown} onClick={() => setShown(true)}>
          <BoundingBoxIcon />
          With box
        </button>
        <button aria-pressed={!shown} onClick={() => setShown(false)}>
          <EyeIcon />
          Image only
        </button>
      </div>
    ) : variant === "chip" ? (
      <button className="bv-chip" aria-pressed={shown} onClick={toggle}>
        <BoundingBoxIcon />
        {shown ? "Hide box" : "Show box"}
      </button>
    ) : variant === "strip" ? (
      <div className="bv-strip-control">
        <span className="bv-strip-label">VIEW</span>
        <BoundingBoxIcon />
        <span>Design box</span>
        <span className="bv-state">{shown ? "Visible" : "Hidden"}</span>
        <button onClick={toggle}>{shown ? "Hide" : "Show"}</button>
      </div>
    ) : (
      <div
        className="bv-menu-wrap"
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
      >
        <button className="bv-menu-button" aria-expanded={open} onClick={() => setOpen(!open)}>
          <SlidersHorizontalIcon />
          Display
          <CaretDownIcon />
        </button>
        {open && (
          <div className="bv-menu">
            <div>
              <BoundingBoxIcon />
              <strong>Design box</strong>
              {switchButton}
            </div>
            <p>Show placement edges and corner handles.</p>
            <small>Your design stays visible.</small>
          </div>
        )}
      </div>
    );
  return (
    <div className={`bv-frame bv-variant-${variant}`}>
      <MarigoldScreen
        state="edit"
        boxVisible={shown}
        toolbar={(c) => (
          <div className="bv-bar">
            {control}
            <MaskToolbar controls={c} />
          </div>
        )}
      />
    </div>
  );
}
