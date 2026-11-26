import { describe, expect, it } from "vitest";
import { pageTitle } from "./pageTitle";

describe("the tab title", () => {
  it.each([
    ["/", "Dashboard · Listings"],
    ["/listings", "Listings"],
    ["/listings/new", "New listing · Listings"],
    ["/listings/christmas-gnome", "christmas-gnome · Listings"],
    ["/listings/christmas%20gnome", "christmas gnome · Listings"],
    ["/listings/christmas-gnome/deploy", "Deploy christmas-gnome · Listings"],
    ["/listings/deploy/run-1", "Deploying listings · Listings"],
    ["/listing-templates", "Listing Templates · Listings"],
    ["/listing-templates/new", "New listing template · Listings"],
    ["/listing-templates/tees", "tees · Listings"],
    ["/batches/new", "New batch · Listings"],
    ["/batches/staging/abc", "Staged designs · Listings"],
    ["/batches/abc", "Batch · Listings"],
    ["/templates", "Mockup Templates · Listings"],
    ["/admin", "Admin · Listings"],
    ["/somewhere-else", "Listings"],
  ])("is right for %s", (pathname, title) => {
    expect(pageTitle(pathname)).toBe(title);
  });
});
