// For frames that show the search box's menu open. It opens the menu the way the
// seller would, so the production box needs nothing for the canvas's sake.
import { type ReactNode, useEffect, useRef } from "react";

export function OpenLabelMenu({
  highlightFirst = false,
  children,
}: {
  /** Press Down, which opens the menu with its first row highlighted. Otherwise
   * click the box, which opens it with nothing highlighted. */
  highlightFirst?: boolean;
  children: ReactNode;
}) {
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const field = root.current?.querySelector<HTMLInputElement>('[role="combobox"]');
    if (highlightFirst) {
      field?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    } else {
      field?.click();
    }
  }, [highlightFirst]);

  return (
    <div ref={root} style={{ display: "contents" }}>
      {children}
    </div>
  );
}
