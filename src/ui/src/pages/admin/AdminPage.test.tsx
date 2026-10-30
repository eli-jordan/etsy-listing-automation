import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, type MockInstance, vi } from "vitest";
import * as shopApi from "../../api/shop";
import type { SaveOutcome, ShopConnections, ShopLookups, ShopSettings } from "../../api/shop";
import { AdminPage } from "./AdminPage";

/* Admin plan, PR 3: the Shop tab against a mocked HTTP surface. Each save
   is revision-checked server-side; these tests prove what the page sends,
   when, and what it shows for every answer. */

function shop(
  overrides: Partial<ShopSettings["listing_defaults"]> = {},
  rest: Partial<ShopSettings> = {},
): ShopSettings {
  return {
    revision: "r1",
    currency: "USD",
    supported_currencies: [
      { code: "USD", name: "US dollar" },
      { code: "EUR", name: "Euro" },
      { code: "NOK", name: "Norwegian krone" },
    ],
    listing_defaults: {
      who_made: "someone_else",
      when_made: "made_to_order",
      is_supply: false,
      production_partner: "Printify",
      shipping_profile: "Printify US standard",
      return_policy: { accepts_returns: false, accepts_exchanges: true, within_days: 30 },
      renewal: "manual",
      ...overrides,
    },
    preferred_print_provider: "Monster Digital",
    ...rest,
  };
}

const CONNECTED: ShopConnections = {
  etsy: {
    state: "connected",
    shop_name: "NaturallyInkedStudio",
    shop_id: 48210377,
    commands: [],
    problem: null,
    signed_in_user_id: 81120455,
    sales_channel: null,
    shop_currency: "USD",
  },
  printify: {
    state: "connected",
    shop_name: "NaturallyInkedStudio",
    shop_id: 19884321,
    commands: [],
    problem: null,
    signed_in_user_id: null,
    sales_channel: "etsy",
    shop_currency: null,
  },
};

function lookups(extra: { shipping?: string[]; providers?: string[] } = {}): ShopLookups {
  return {
    etsy: {
      available: true,
      problem: null,
      production_partners: ["Printify"],
      shipping_profiles: [
        "Printify US standard",
        "Printify EU standard",
        ...(extra.shipping ?? []),
      ],
      return_policies: [
        {
          terms: { accepts_returns: false, accepts_exchanges: true, within_days: 30 },
          label: "exchanges within 30 days",
        },
        {
          terms: { accepts_returns: true, accepts_exchanges: true, within_days: 14 },
          label: "returns and exchanges within 14 days",
        },
      ],
    },
    printify: {
      available: true,
      problem: null,
      print_providers: ["Monster Digital", "SwiftPOD", ...(extra.providers ?? [])],
    },
  };
}

const OFFLINE: ShopLookups = {
  etsy: {
    available: false,
    problem: "Could not reach Etsy: 503",
    production_partners: [],
    shipping_profiles: [],
    return_policies: [],
  },
  printify: { available: false, problem: "Could not reach Printify", print_providers: [] },
};

let save: MockInstance<typeof shopApi.saveShop>;
let getLookups: MockInstance<typeof shopApi.getShopLookups>;

function saved(next: ShopSettings): SaveOutcome {
  return { kind: "saved", shop: next };
}

beforeEach(() => {
  vi.spyOn(shopApi, "getShop").mockResolvedValue(shop());
  vi.spyOn(shopApi, "getShopConnections").mockResolvedValue(CONNECTED);
  getLookups = vi.spyOn(shopApi, "getShopLookups").mockResolvedValue(lookups());
  save = vi.spyOn(shopApi, "saveShop").mockImplementation(async (revision, changes) =>
    saved({
      ...shop(),
      revision: revision + "+",
      ...("currency" in changes ? { currency: changes.currency ?? "USD" } : {}),
    }),
  );
});

afterEach(() => vi.restoreAllMocks());

function scrim(): HTMLElement {
  const element = document.querySelector<HTMLElement>(".sa-scrim");
  if (!element) throw new Error("no dialog backdrop");
  return element;
}

async function openDefaults() {
  render(<AdminPage />);
  await userEvent.click(await screen.findByRole("link", { name: "Listing defaults" }));
  await screen.findByRole("heading", { name: "Listing defaults" });
}

describe("Admin page shell", () => {
  it("opens on Connected shops and keeps Settings visibly unavailable", async () => {
    render(<AdminPage />);
    expect(await screen.findByRole("heading", { name: "Connected shops" })).toBeVisible();
    const settings = screen.getByText("Settings").closest("[aria-disabled]");
    expect(settings).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  });
});

describe("Connected shops", () => {
  it("shows both configured shops as read-only identities", async () => {
    render(<AdminPage />);
    const etsy = await screen.findByTestId("connection-etsy");
    expect(within(etsy).getByText("NaturallyInkedStudio")).toBeInTheDocument();
    expect(within(etsy).getByText("#48210377")).toBeInTheDocument();
    expect(within(etsy).getByText(/Read-only/)).toBeInTheDocument();
    const printify = screen.getByTestId("connection-printify");
    expect(within(printify).getByText("#19884321")).toBeInTheDocument();
    expect(within(printify).getByText(/Connected to Etsy/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /switch/i })).not.toBeInTheDocument();
  });

  it("says Not connected with the command each missing piece needs", async () => {
    vi.spyOn(shopApi, "getShopConnections").mockResolvedValue({
      etsy: {
        ...CONNECTED.etsy,
        state: "not_connected",
        shop_id: null,
        commands: ["etsy-listings auth etsy", "etsy-listings setup"],
      },
      printify: {
        ...CONNECTED.printify,
        state: "not_connected",
        shop_name: null,
        shop_id: null,
        commands: ["etsy-listings auth printify"],
      },
    });
    render(<AdminPage />);

    const etsy = await screen.findByTestId("connection-etsy");
    expect(within(etsy).getByText("Not connected")).toBeInTheDocument();
    expect(within(etsy).getByText("etsy-listings auth etsy")).toBeInTheDocument();
    expect(within(etsy).getByText("etsy-listings setup")).toBeInTheDocument();
    const printify = screen.getByTestId("connection-printify");
    expect(within(printify).getByText("etsy-listings auth printify")).toBeInTheDocument();
    expect(within(printify).queryByText("etsy-listings setup")).not.toBeInTheDocument();
  });

  it("keeps a configured identity when its lookup fails", async () => {
    vi.spyOn(shopApi, "getShopConnections").mockResolvedValue({
      ...CONNECTED,
      etsy: { ...CONNECTED.etsy, state: "lookup_failed", problem: "Could not reach Etsy: 503" },
    });
    render(<AdminPage />);

    const etsy = await screen.findByTestId("connection-etsy");
    expect(within(etsy).getByText("NaturallyInkedStudio")).toBeInTheDocument();
    expect(within(etsy).getByText(/Could not reach Etsy/)).toBeInTheDocument();
    expect(within(etsy).queryByText("Not connected")).not.toBeInTheDocument();
  });
});

describe("Currency", () => {
  async function openDialog() {
    render(<AdminPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Change currency…" }));
    return screen.getByRole("dialog", { name: /converts nothing/ });
  }

  it("opens without saving and holds Change back until acknowledged", async () => {
    const dialog = await openDialog();
    expect(save).not.toHaveBeenCalled();
    const confirm = within(dialog).getByRole("button", { name: "Change to EUR" });
    expect(confirm).toBeDisabled();

    await userEvent.selectOptions(within(dialog).getByLabelText("New currency"), "NOK");
    expect(within(dialog).getByRole("button", { name: "Change to NOK" })).toBeDisabled();
    expect(within(dialog).getByText(/Your Etsy shop sells in USD/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("option", { name: /USD/ })).not.toBeInTheDocument();

    await userEvent.click(within(dialog).getByLabelText(/prices won't be converted/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Change to NOK" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("r1", { currency: "NOK" });
    expect(await screen.findByText(/Currency: NOK/)).toBeInTheDocument();
  });

  it("says saved prices keep their currency rather than being reread", async () => {
    const dialog = await openDialog();
    expect(within(dialog).getByText(/keep the currency written beside them/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/is read as/)).not.toBeInTheDocument();
  });

  it.each([
    [
      "Keep",
      (d: HTMLElement) => userEvent.click(within(d).getByRole("button", { name: "Keep USD" })),
    ],
    [
      "close",
      (d: HTMLElement) => userEvent.click(within(d).getByRole("button", { name: "Cancel" })),
    ],
    ["Escape", () => userEvent.keyboard("{Escape}")],
    ["backdrop", () => userEvent.click(scrim())],
  ])("cancels with %s, saving nothing and returning focus", async (_, cancel) => {
    const dialog = await openDialog();
    await userEvent.click(within(dialog).getByLabelText(/prices won't be converted/));
    await cancel(dialog);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
    const trigger = screen.getByRole("button", { name: "Change currency…" });
    expect(trigger).toHaveFocus();

    await userEvent.click(trigger);
    expect(screen.getByLabelText(/prices won't be converted/)).not.toBeChecked();
  });

  it("stays open with the error when the save fails", async () => {
    save.mockRejectedValueOnce(new shopApi.ShopApiError("could not save shop.yaml"));
    const dialog = await openDialog();
    await userEvent.click(within(dialog).getByLabelText(/prices won't be converted/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Change to EUR" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("could not save shop.yaml");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("keeps clicks inside the dialog from dismissing it, and Tab inside it", async () => {
    const dialog = await openDialog();
    await userEvent.click(within(dialog).getByText(/Read this before/));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    for (let i = 0; i < 8; i++) await userEvent.tab();
    expect(dialog.contains(document.activeElement)).toBe(true);
  });
});

describe("How your items are made", () => {
  it("derives Print on demand from the three saved values", async () => {
    await openDefaults();
    expect(screen.getByRole("radio", { name: /Print on demand/ })).toBeChecked();
    expect(screen.getByLabelText("What Print on demand sets")).toHaveTextContent(
      "Another company or person",
    );
    expect(screen.queryByLabelText("Who made it")).not.toBeInTheDocument();
  });

  it("shows Custom for values that do not match, with their selectors", async () => {
    vi.spyOn(shopApi, "getShop").mockResolvedValue(shop({ who_made: "i_did" }));
    await openDefaults();
    expect(screen.getByRole("radio", { name: /Custom/ })).toBeChecked();
    expect(screen.getByLabelText("Who made it")).toHaveValue("i_did");
  });

  it("choosing Custom alone changes only the visible controls", async () => {
    await openDefaults();
    await userEvent.click(screen.getByRole("radio", { name: /Custom/ }));
    expect(screen.getByLabelText("Who made it")).toHaveValue("someone_else");
    expect(screen.getByLabelText("When it was made")).toHaveValue("made_to_order");
    expect(save).not.toHaveBeenCalled();
  });

  it("choosing Print on demand writes all three values in one save", async () => {
    vi.spyOn(shopApi, "getShop").mockResolvedValue(shop({ who_made: "i_did", is_supply: true }));
    await openDefaults();
    await userEvent.click(screen.getByRole("radio", { name: /Print on demand/ }));

    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("r1", {
      who_made: "someone_else",
      when_made: "made_to_order",
      is_supply: false,
    });
    expect(await screen.findByLabelText("What Print on demand sets")).toBeInTheDocument();
  });
});

describe("Listing defaults", () => {
  it("saves a selector on blur, once, and not when unchanged", async () => {
    await openDefaults();
    const renewal = screen.getByLabelText("Renewal");
    renewal.focus();
    fireEvent.blur(renewal);
    expect(save).not.toHaveBeenCalled();

    fireEvent.change(renewal, { target: { value: "auto" } });
    expect(save).not.toHaveBeenCalled();
    fireEvent.blur(renewal);
    fireEvent.blur(renewal);

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith("r1", { renewal: "auto" });
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("serializes saves, each naming the revision the last one returned", async () => {
    let release!: () => void;
    save.mockImplementationOnce(
      (revision: string) =>
        new Promise<SaveOutcome>((resolve) => {
          release = () => resolve(saved({ ...shop(), revision: revision + "+" }));
        }),
    );
    await openDefaults();
    fireEvent.change(screen.getByLabelText("Renewal"), { target: { value: "auto" } });
    fireEvent.blur(screen.getByLabelText("Renewal"));
    fireEvent.change(screen.getByLabelText("Shipping profile"), {
      target: { value: "Printify EU standard" },
    });
    fireEvent.blur(screen.getByLabelText("Shipping profile"));

    expect(screen.getByText("Saving…")).toBeInTheDocument();
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    // The second waits for the first's answer and the revision it carries.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(save).toHaveBeenCalledTimes(1);
    await act(async () => release());
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save.mock.calls[1]).toEqual(["r1+", { shipping_profile: "Printify EU standard" }]);
  });

  it("keeps a refused value visible with its field error", async () => {
    save.mockResolvedValueOnce({
      kind: "invalid",
      message: "bad",
      fieldErrors: { renewal: "Input should be 'manual' or 'auto'" },
    });
    await openDefaults();
    const renewal = screen.getByLabelText("Renewal");
    fireEvent.change(renewal, { target: { value: "auto" } });
    fireEvent.blur(renewal);

    expect(await screen.findByText("Input should be 'manual' or 'auto'")).toBeInTheDocument();
    expect(renewal).toHaveValue("auto");
    expect(screen.getByText("Not saved")).toBeInTheDocument();
  });

  it("asks for a reload after a conflict and edits nothing until then", async () => {
    save.mockResolvedValueOnce({ kind: "conflict", message: "shop.yaml changed on disk" });
    await openDefaults();
    fireEvent.change(screen.getByLabelText("Renewal"), { target: { value: "auto" } });
    fireEvent.blur(screen.getByLabelText("Renewal"));

    expect(await screen.findByText(/changed on disk/)).toBeInTheDocument();
    expect(screen.getByLabelText("Renewal")).toBeDisabled();
    vi.spyOn(shopApi, "getShop").mockResolvedValue(shop({ renewal: "auto" }, { revision: "r9" }));
    await userEvent.click(screen.getByRole("button", { name: "Reload shop.yaml" }));

    await waitFor(() => expect(screen.getByLabelText("Renewal")).toBeEnabled());
    expect(screen.getByLabelText("Renewal")).toHaveValue("auto");
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("saves a return policy by its terms", async () => {
    await openDefaults();
    const policy = screen.getByLabelText("Return policy");
    await userEvent.selectOptions(policy, "returns and exchanges within 14 days");
    fireEvent.blur(policy);

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith("r1", {
        return_policy: { accepts_returns: true, accepts_exchanges: true, within_days: 14 },
      }),
    );
  });

  it("keeps a saved choice the lookup no longer offers, with a warning", async () => {
    vi.spyOn(shopApi, "getShop").mockResolvedValue(shop({ shipping_profile: "Retired profile" }));
    await openDefaults();
    expect(screen.getByLabelText("Shipping profile")).toHaveValue("Retired profile");
    expect(
      await screen.findByText(/Retired profile is not in the list Etsy returned/),
    ).toBeInTheDocument();
  });

  it("opens one info card at a time and closes it with Escape", async () => {
    await openDefaults();
    await userEvent.click(screen.getByRole("button", { name: "About Renewal" }));
    expect(screen.getByText(/Etsy listings expire after four months/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "About Shipping profile" }));
    expect(screen.queryByText(/Etsy listings expire after four months/)).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByText(/Shipping prices and processing time/)).not.toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });
});

describe("Lookups", () => {
  it("opens Create in a new tab and refreshes on return without choosing for the seller", async () => {
    await openDefaults();
    const creates = screen.getAllByRole("link", { name: /Create on Etsy/ });
    expect(creates.map((a) => a.getAttribute("href"))).toEqual([
      "https://www.etsy.com/your/shops/me/production-partners",
      "https://www.etsy.com/your/shops/me/tools/shipping-profiles",
      "https://www.etsy.com/your/shops/me/policies",
    ]);
    for (const create of creates) {
      expect(create).toHaveAttribute("target", "_blank");
      expect(create).toHaveAttribute("rel", expect.stringContaining("noopener"));
    }

    getLookups.mockResolvedValueOnce(lookups({ shipping: ["Printify UK standard"] }));
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });

    expect(await screen.findByText(/New from Etsy: Printify UK standard/)).toBeInTheDocument();
    expect(screen.getByLabelText("Shipping profile")).toHaveValue("Printify US standard");
    expect(save).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Use it" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith("r1", { shipping_profile: "Printify UK standard" }),
    );
  });

  it("returning with nothing new saves nothing", async () => {
    await openDefaults();
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    await waitFor(() => expect(getLookups).toHaveBeenCalledTimes(2));
    expect(screen.queryByText(/New from/)).not.toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it("keeps saved choices through a failure and retries without saving", async () => {
    getLookups.mockResolvedValueOnce(OFFLINE);
    await openDefaults();

    expect(await screen.findByText(/Could not reach Etsy or Printify/)).toBeInTheDocument();
    expect(screen.getByLabelText("Shipping profile")).toHaveValue("Printify US standard");
    expect(screen.getByLabelText("Shipping profile")).toBeDisabled();
    expect(screen.getByLabelText("Renewal")).toBeEnabled();

    await userEvent.click(screen.getByRole("button", { name: "Retry lookups" }));
    await waitFor(() => expect(screen.getByLabelText("Shipping profile")).toBeEnabled());
    expect(getLookups).toHaveBeenCalledTimes(2);
    expect(save).not.toHaveBeenCalled();
  });

  it("offers the whole provider catalog with the preference first", async () => {
    await openDefaults();
    const provider = screen.getByLabelText("Preferred print provider");
    await waitFor(() =>
      expect(
        within(provider)
          .getAllByRole("option")
          .map((o) => o.textContent),
      ).toEqual(["Monster Digital", "SwiftPOD"]),
    );
    expect(screen.getByRole("link", { name: /Browse on Printify/ })).toHaveAttribute(
      "target",
      "_blank",
    );
  });
});
