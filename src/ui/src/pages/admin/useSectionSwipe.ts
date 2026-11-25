import type { RefObject } from "react";
import { resist } from "../../phone/swipe";
import { useIsPhone } from "../../phone/usePhone";
import { useSwipe } from "../../phone/useSwipe";
import { adjacentSection, type Section } from "./adminSections";

type Pick = (section: Section) => void;

/** A new section starts at its top, under the chips (PhoneSections). */
function toTop() {
  window.scrollTo({ top: 0 });
}

/** The section content's lean with a finger dragging it sideways, damped
 * like a native edge; 0 puts it back. */
function lean(element: HTMLElement | null, offset: number) {
  if (!element) return;
  element.style.transition = offset ? "none" : "";
  element.style.transform = offset ? `translateX(${resist(offset)}px)` : "";
}

/** A sideways swipe on the section's content moves to the section beside
 * it, and the content leans with the finger on the way. Phone only, and a
 * finger only (`useSwipe`): fields, sliders and sideways scrollers inside
 * keep their own drags. */
export function useSectionSwipe(
  content: RefObject<HTMLElement | null>,
  section: Section,
  onPick: Pick,
): void {
  const isPhone = useIsPhone();
  useSwipe(content, {
    axis: "x",
    enabled: isPhone,
    onDrag: (offset) => lean(content.current, offset),
    onSwipe: (direction) => {
      lean(content.current, 0);
      if (direction !== "left" && direction !== "right") return;
      const next = adjacentSection(section, direction);
      if (next === null) return;
      onPick(next);
      toTop();
    },
  });
}
