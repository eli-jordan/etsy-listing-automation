import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PhoneSections } from "./PhoneSections";

describe("PhoneSections", () => {
  it("marks the open section and picks another on a tap", async () => {
    const onPick = vi.fn();
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    render(<PhoneSections section="rendering" backupPage="status" onPick={onPick} />);

    const nav = screen.getByRole("navigation", { name: "Admin sections" });
    expect(screen.getByRole("link", { name: "Template rendering" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(nav.querySelectorAll("a")).toHaveLength(5);

    await userEvent.click(screen.getByRole("link", { name: "Listing defaults" }));
    expect(onPick).toHaveBeenCalledWith("defaults");
    expect(scrollTo).toHaveBeenCalledWith({ top: 0 });
    scrollTo.mockRestore();
  });

  it("says Backup is off before it is set up, with no pages under it", () => {
    render(<PhoneSections section="backup" backupPage="status" onPick={() => {}} />);

    expect(screen.getByRole("link", { name: /Backup/ })).toHaveTextContent("Backupoff");
    expect(screen.queryByRole("link", { name: "Setup" })).toBeNull();
  });
});
