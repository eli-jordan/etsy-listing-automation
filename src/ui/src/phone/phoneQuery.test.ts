import { describe, expect, it } from "vitest";
import mainSource from "../main.tsx?raw";
import { PHONE_LANDSCAPE_QUERY, PHONE_QUERY } from "./usePhone";

// CSS has no constants a media query can name, so each stylesheet spells the
// phone query out. This holds every spelling to usePhone.ts: a rule written
// for "(max-width: 700px)" alone would leave a sideways phone on half the
// phone layout.
const stylesheets = import.meta.glob<string>("../**/*.css", {
  query: "?raw",
  import: "default",
  eager: true,
});

const MOTION = " and (prefers-reduced-motion: no-preference)";

function mediaQueries(css: string): string[] {
  return [...css.matchAll(/@media([^{]+)\{/g)].map((match) =>
    (match[1] ?? "").replace(/\s+/g, " ").trim(),
  );
}

function aboutThePhone(query: string): boolean {
  return query.includes("700px") || query.includes("orientation: landscape");
}

/** The query with a reduced-motion condition taken off each clause. */
function withoutMotion(query: string): string {
  return query
    .split(",")
    .map((clause) => clause.trim().replace(MOTION, ""))
    .join(", ");
}

describe("the phone query in the stylesheets", () => {
  it("is the one usePhone.ts defines, or its sideways clause", () => {
    const misspelt = Object.entries(stylesheets).flatMap(([file, css]) =>
      mediaQueries(css)
        .filter(aboutThePhone)
        .filter((query) => ![PHONE_QUERY, PHONE_LANDSCAPE_QUERY].includes(withoutMotion(query)))
        .map((query) => `${file}: @media ${query}`),
    );
    expect(misspelt).toEqual([]);
  });

  it("finds the stylesheets it checks", () => {
    expect(Object.keys(stylesheets)).toEqual(
      expect.arrayContaining(["./shell.css", "../index.css", "../pages/admin/admin.css"]),
    );
  });
});

describe("the phone stylesheet", () => {
  it("is main.tsx's last import, so its rules come after every desktop rule", () => {
    const imports = [...mainSource.matchAll(/(?:^import|\bfrom)\s+["']([^"']+)["']/gm)].map(
      (match) => match[1],
    );
    expect(imports.at(-1)).toBe("./phone/index.css");
  });
});
