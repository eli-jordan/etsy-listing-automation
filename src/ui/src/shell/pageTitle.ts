/** The app's name, as the sidebar's wordmark says it. */
export const APP_NAME = "Listings";

/** The browser tab's title for a route: the page first, so a row of tabs
 * stays tellable apart once they narrow, then the app. A listing or
 * template page leads with its name. */
export function pageTitle(pathname: string): string {
  const [section = "", ...rest] = pathname.split("/").filter(Boolean).map(decode);
  const page = SECTIONS[section]?.(rest) ?? null;
  return page === null || page === APP_NAME ? APP_NAME : `${page} · ${APP_NAME}`;
}

const SECTIONS: Record<string, (rest: string[]) => string> = {
  "": () => "Dashboard",
  listings: listingPage,
  "listing-templates": ([name]) => {
    if (name === undefined) return "Listing Templates";
    return name === "new" ? "New listing template" : name;
  },
  batches: ([name]) => {
    if (name === "new") return "New batch";
    return name === "staging" ? "Staged designs" : "Batch";
  },
  templates: () => "Mockup Templates",
  admin: () => "Admin",
};

function listingPage([name, sub]: string[]): string {
  if (name === undefined) return "Listings";
  if (name === "new") return "New listing";
  if (name === "deploy") return "Deploying listings";
  return sub === "deploy" ? `Deploy ${name}` : name;
}

function decode(part: string): string {
  try {
    return decodeURIComponent(part);
  } catch {
    return part;
  }
}
