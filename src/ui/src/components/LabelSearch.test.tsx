import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { LabelSearch } from "./LabelSearch";

/** The caller owns both values, so a test needs a caller. */
function Box({
  items,
  pills = [],
  text = "",
}: {
  items: string[][];
  pills?: string[];
  text?: string;
}) {
  const [on, setOn] = useState(pills);
  const [query, setQuery] = useState(text);
  return <LabelSearch items={items} on={on} onOn={setOn} query={query} onQuery={setQuery} />;
}

const ITEMS = [
  ["theme:christmas", "model:female"],
  ["theme:christmas", "shot:flat lay"],
  ["theme:summer", "cosy"],
];

const field = () => screen.getByRole("combobox");
const offered = () =>
  screen.queryAllByRole("option").map((o) => o.querySelector("span")?.textContent);
const pills = () =>
  screen.queryAllByRole("button", { name: /^Remove / }).map((b) => b.parentElement?.textContent);
const highlighted = () =>
  screen
    .queryAllByRole("option")
    .filter((o) => o.getAttribute("aria-selected") === "true")
    .map((o) => o.querySelector("span")?.textContent);
const press = (key: string) => fireEvent.keyDown(field(), { key });
const type = (value: string) => fireEvent.change(field(), { target: { value } });
const clickBox = () => fireEvent.click(field());

describe("the input table", () => {
  it("opens on a click with every label not already a pill", () => {
    render(<Box items={ITEMS} pills={["theme:christmas"]} />);
    clickBox();
    expect(offered()).toEqual(["model:female", "shot:flat lay", "theme:summer", "cosy"]);
  });

  it("opens on Down", () => {
    render(<Box items={ITEMS} />);
    press("ArrowDown");
    expect(offered()).toHaveLength(5);
  });

  it("walks the highlight through all groups and wraps at both ends", () => {
    render(<Box items={ITEMS} />);
    clickBox();
    expect(highlighted()).toEqual([]);
    press("ArrowDown");
    expect(highlighted()).toEqual(["model:female"]);
    press("ArrowDown");
    expect(highlighted()).toEqual(["shot:flat lay"]);
    press("ArrowUp");
    press("ArrowUp");
    expect(highlighted()).toEqual(["cosy"]);
    press("ArrowDown");
    expect(highlighted()).toEqual(["model:female"]);
  });

  it("starts from the last label on Up", () => {
    render(<Box items={ITEMS} />);
    clickBox();
    press("ArrowUp");
    expect(highlighted()).toEqual(["cosy"]);
  });

  it("takes the highlighted label on Enter, keeping focus in the box", () => {
    render(<Box items={ITEMS} text="chr" />);
    field().focus();
    clickBox();
    press("ArrowDown");
    press("Enter");
    expect(pills()).toEqual(["theme:christmas"]);
    expect(field()).toHaveValue("");
    expect(offered()).toEqual([]);
    expect(field()).toHaveFocus();
  });

  it("keeps the text as a title search on Enter with nothing highlighted", () => {
    render(<Box items={ITEMS} />);
    type("chr");
    press("Enter");
    expect(pills()).toEqual([]);
    expect(field()).toHaveValue("chr");
    expect(offered()).toEqual([]);
  });

  it("takes a clicked label as Enter does", () => {
    render(<Box items={ITEMS} text="chr" />);
    clickBox();
    field().blur();
    fireEvent.click(screen.getByRole("option"));
    expect(pills()).toEqual(["theme:christmas"]);
    expect(field()).toHaveValue("");
    expect(offered()).toEqual([]);
    expect(field()).toHaveFocus();
  });

  it("closes on Esc, clearing the highlight and keeping the text", () => {
    render(<Box items={ITEMS} />);
    type("chr");
    press("ArrowDown");
    press("Escape");
    expect(offered()).toEqual([]);
    expect(field()).toHaveValue("chr");
    clickBox();
    expect(highlighted()).toEqual([]);
  });

  it("removes the last pill on Backspace in an empty box, and only then", () => {
    render(<Box items={ITEMS} pills={["theme:christmas", "model:female"]} text="x" />);
    press("Backspace");
    expect(pills()).toHaveLength(2);
    type("");
    press("Backspace");
    expect(pills()).toEqual(["theme:christmas"]);
  });

  it("removes one pill with its ×", () => {
    render(<Box items={ITEMS} pills={["theme:christmas", "model:female"]} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove theme:christmas" }));
    expect(pills()).toEqual(["model:female"]);
  });
});

describe("what the dropdown offers", () => {
  it("opens from the first letter, on any part of a label, nothing highlighted", () => {
    render(<Box items={ITEMS} />);
    type("t");
    press("ArrowDown");
    type("h");
    expect(offered()).toEqual(["shot:flat lay", "theme:christmas", "theme:summer"]);
    expect(highlighted()).toEqual([]);
    expect(field()).not.toHaveAttribute("aria-activedescendant");
  });

  it("finds a whole group by its prefix", () => {
    render(<Box items={ITEMS} />);
    type("theme");
    expect(offered()).toEqual(["theme:christmas", "theme:summer"]);
  });

  it("opens nothing for text in no label", () => {
    render(<Box items={ITEMS} />);
    type("zebra");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(field()).toHaveAttribute("aria-expanded", "false");
  });

  it("puts the typed part in bold", () => {
    render(<Box items={ITEMS} />);
    type("CHR");
    expect(screen.getByRole("option").querySelector("strong")).toHaveTextContent("chr");
  });

  it("counts the templates that would remain", () => {
    render(<Box items={[["a", "b"], ["b"], ["b"]]} pills={["a"]} />);
    clickBox();
    expect(screen.getByRole("option")).toHaveTextContent(/1$/);
  });

  it("orders groups A to Z under headings, with plain labels under Other last", () => {
    render(<Box items={[["cosy", "zebra:a"], ["alpha:b"], ["theme:c"]]} />);
    clickBox();
    const list = within(screen.getByRole("listbox")).getAllByText(/./, {
      selector: ".label-search__group, [role=option] > span:first-child",
    });
    expect(list.map((el) => el.textContent)).toEqual([
      "alpha",
      "alpha:b",
      "theme",
      "theme:c",
      "zebra",
      "zebra:a",
      "Other",
      "cosy",
    ]);
  });

  it("shows no headings when nothing on offer has a prefix", () => {
    render(<Box items={[["cosy", "theme:c"], ["bright"]]} />);
    type("o");
    expect(offered()).toEqual(["cosy"]);
    expect(screen.queryByText("Other")).not.toBeInTheDocument();
  });

  it("orders a group: labels that narrow, then by count", () => {
    const swap = ["t:a-swap"];
    const items = [["on", "t:a2"], ["on", "t:a2"], ["on", "t:a1"], swap, swap, swap];
    render(<Box items={items} pills={["on"]} />);
    type("a");
    expect(offered()).toEqual(["t:a2", "t:a1", "t:a-swap"]);
  });

  it("ranks text starting the part after the colon ahead of a higher count", () => {
    render(<Box items={[["theme:orchre"], ["theme:orchre"], ["Theme:Christmas"]]} />);
    type("chr");
    expect(offered()).toEqual(["Theme:Christmas", "theme:orchre"]);
  });

  it("puts labels starting with the typed text ahead of a higher count", () => {
    render(<Box items={[["xab"], ["xab"], ["abx"]]} />);
    type("ab");
    expect(offered()).toEqual(["abx", "xab"]);
  });
});

describe("a label that shares no template with the pills", () => {
  const items = [["theme:christmas"], ["theme:christmas"], ["theme:summer"], ["theme:summer"]];

  it("says it replaces them and shows its own total", () => {
    render(<Box items={items} pills={["theme:christmas"]} />);
    clickBox();
    const row = screen.getByRole("option", { name: /theme:summer/ });
    expect(row).toHaveTextContent("replaces theme:christmas");
    expect(row).toHaveTextContent(/2$/);
  });

  it("replaces the pills when picked", () => {
    render(<Box items={items} pills={["theme:christmas"]} />);
    clickBox();
    press("ArrowDown");
    press("Enter");
    expect(pills()).toEqual(["theme:summer"]);
  });

  it("is not marked when it narrows", () => {
    render(<Box items={[["a", "b"]]} pills={["a"]} />);
    clickBox();
    expect(screen.getByRole("option")).not.toHaveTextContent("replaces");
  });
});

describe("the placeholder", () => {
  it("offers labels until there is a pill, then titles", () => {
    render(<Box items={ITEMS} />);
    expect(field()).toHaveAttribute("placeholder", "Search or add a label…");
    clickBox();
    press("ArrowDown");
    press("Enter");
    expect(field()).toHaveAttribute("placeholder", "Search titles…");
  });
});

describe("the ARIA combobox", () => {
  it("names its popup and its highlight only while they exist", () => {
    render(<Box items={ITEMS} />);
    expect(field()).toHaveAttribute("aria-expanded", "false");
    expect(field()).toHaveAttribute("aria-autocomplete", "list");
    expect(field()).not.toHaveAttribute("aria-controls");

    press("ArrowDown");
    const listbox = screen.getByRole("listbox", { name: "Labels" });
    expect(field()).toHaveAttribute("aria-expanded", "true");
    expect(field()).toHaveAttribute("aria-controls", listbox.id);
    const [first] = screen.getAllByRole("option");
    expect(field()).toHaveAttribute("aria-activedescendant", first?.id);
    expect(first).toHaveAttribute("aria-selected", "true");
  });

  it("gives two boxes on one page their own ids", () => {
    render(
      <>
        <Box items={ITEMS} />
        <Box items={ITEMS} />
      </>,
    );
    const [one, two] = screen.getAllByRole("combobox");
    fireEvent.keyDown(one as Element, { key: "ArrowDown" });
    fireEvent.keyDown(two as Element, { key: "ArrowDown" });
    const ids = [
      ...screen.getAllByRole("listbox").map((list) => list.id),
      ...screen.getAllByRole("option").map((option) => option.id),
    ];
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("hand-edited labels", () => {
  const items = [["Theme:Christmas"], ["theme:christmas", "Cosy"], ["THEME:summer"]];

  it("matches text whatever the label's case, and marks it as written", () => {
    render(<Box items={[["Theme:Christmas"]]} />);
    type("chr");
    expect(offered()).toEqual(["Theme:Christmas"]);
    expect(screen.getByRole("option").querySelector("strong")).toHaveTextContent("Chr");
  });

  it("offers two spellings of a label once, counting both", () => {
    render(<Box items={items} />);
    type("chr");
    expect(offered()).toEqual(["Theme:Christmas"]);
    expect(screen.getByRole("option")).toHaveTextContent(/2$/);
  });

  it("keeps a group together across spellings", () => {
    render(<Box items={items} />);
    clickBox();
    expect(screen.getAllByText(/^theme$/i)).toHaveLength(1);
  });

  it("does not offer a label already on as a pill in another case", () => {
    render(<Box items={items} pills={["theme:christmas"]} />);
    clickBox();
    expect(offered()).not.toContain("Theme:Christmas");
  });

  it("counts a template holding a pill in another case", () => {
    render(<Box items={[["Theme:Christmas", "cosy"]]} pills={["theme:christmas"]} />);
    clickBox();
    expect(screen.getByRole("option", { name: /cosy/ })).not.toHaveTextContent("replaces");
  });

  it("files a label with nothing before its colon under Other", () => {
    render(<Box items={[[":odd"], ["theme:x"]]} />);
    clickBox();
    expect(screen.getByText("Other")).toBeInTheDocument();
  });
});

describe("keyboard and focus", () => {
  it("closes on a click outside, forgetting the highlight", () => {
    render(<Box items={ITEMS} />);
    clickBox();
    press("ArrowDown");
    fireEvent.mouseDown(document.body);
    expect(offered()).toEqual([]);
    clickBox();
    expect(highlighted()).toEqual([]);
  });

  it("closes when Tab leaves the box", () => {
    render(<Box items={ITEMS} />);
    clickBox();
    press("ArrowDown");
    press("Tab");
    expect(offered()).toEqual([]);
    clickBox();
    expect(highlighted()).toEqual([]);
  });

  it("returns focus to the box when a pill's × goes", () => {
    render(<Box items={ITEMS} pills={["theme:christmas"]} />);
    const remove = screen.getByRole("button", { name: "Remove theme:christmas" });
    remove.focus();
    fireEvent.click(remove);
    expect(field()).toHaveFocus();
  });

  it("forgets the highlight when Backspace changes what is on offer", () => {
    render(<Box items={ITEMS} pills={["theme:christmas"]} />);
    clickBox();
    press("ArrowDown");
    press("Backspace");
    expect(highlighted()).toEqual([]);
  });

  it("highlights nothing when Down finds nothing to offer", () => {
    const { rerender } = render(<Box items={[]} text="x" />);
    press("ArrowDown");
    rerender(<Box items={[["x"]]} text="x" />);
    clickBox();
    expect(highlighted()).toEqual([]);
  });

  it("keeps the highlighted row in view", () => {
    const scroll = vi.mocked(Element.prototype.scrollIntoView);
    scroll.mockClear();
    render(<Box items={ITEMS} />);
    press("ArrowDown");
    expect(scroll.mock.contexts.at(-1)).toBe(screen.getAllByRole("option")[0]);
  });
});
