import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, type MockInstance, vi } from "vitest";
import * as shopApi from "../../api/shop";
import * as settingsApi from "../../api/workspaceSettings";
import type {
  SaveOutcome,
  ShopChanges,
  ShopConnections,
  ShopLookups,
  ShopSettings,
} from "../../api/shop";
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
  const weights = {
    reviews: 30,
    favourites_per_day: 30,
    search_rank: 20,
    views_per_day: 10,
    shop_sales: 5,
    shop_rating: 5,
  };
  vi.spyOn(settingsApi, "getSettings").mockResolvedValue({
    revision: "s1",
    concurrency: 1,
    providers: [{ name: "codex", enabled: true }],
    weights,
    default_weights: weights,
    step_limit_minutes: 5,
    run_limit_minutes: 20,
  });
  vi.spyOn(settingsApi, "getModelCatalogs").mockResolvedValue({
    cache_seconds: 1800,
    providers: {},
  });
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
  it("opens on Connected shops and preserves pending Settings edits across navigation", async () => {
    render(<AdminPage />);
    expect(await screen.findByRole("heading", { name: "Connected shops" })).toBeVisible();
    expect(
      screen.queryByRole("slider", { name: "Listings drafted at once" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: /Settings/ }));
    const slider = await screen.findByRole("slider", { name: "Listings drafted at once" });
    fireEvent.change(slider, { target: { value: "4" } });
    fireEvent.click(screen.getByRole("link", { name: /Shop shop.yaml/ }));
    expect(
      screen.queryByRole("slider", { name: "Listings drafted at once" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: /Settings/ }));
    expect(screen.getByRole("slider", { name: "Listings drafted at once" })).toHaveValue("4");
    expect(settingsApi.getSettings).toHaveBeenCalledTimes(1);
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

  it.each(["title", "warning copy"])(
    "keeps every forward and backward Tab inside after clicking the %s",
    async (target) => {
      const dialog = await openDialog();
      const content =
        target === "title"
          ? within(dialog).getByRole("heading", { name: /converts nothing/ })
          : within(dialog).getByText(/Read this before/);
      for (const shift of [false, true]) {
        await userEvent.click(content);
        expect(screen.getByRole("dialog")).toBeInTheDocument();
        for (let i = 0; i < 10; i++) {
          await userEvent.tab({ shift });
          expect(dialog.contains(document.activeElement)).toBe(true);
        }
      }
      await userEvent.keyboard("{Escape}");
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Change currency…" })).toHaveFocus();
      expect(save).not.toHaveBeenCalled();
    },
  );
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

  /** shop.yaml behind the mocked endpoint: each save applies its changes
   * and returns the next revision, or waits/fails when a test says so. */
  function fileServer() {
    let file = shop();
    let n = 1;
    const answers: ((apply: () => SaveOutcome) => Promise<SaveOutcome>)[] = [];
    save.mockImplementation((revision, changes) => {
      const apply = () => {
        expect(revision).toBe(file.revision);
        n += 1;
        const defaults = Object.fromEntries(
          Object.entries(changes).filter(([key]) => key !== "currency"),
        );
        file = {
          ...file,
          revision: `r${n}`,
          listing_defaults: {
            ...file.listing_defaults,
            ...defaults,
          } as ShopSettings["listing_defaults"],
        };
        return saved(file);
      };
      const answer = answers.shift();
      return answer ? answer(apply) : Promise.resolve(apply());
    });
    return {
      file: () => file,
      /** The next save waits until the returned function answers it. */
      hold() {
        let release: (() => void) | undefined;
        answers.push(
          (apply) =>
            new Promise((resolve) => {
              release = () => resolve(apply());
            }),
        );
        return async () => {
          await waitFor(() => expect(release).toBeDefined());
          await act(async () => release?.());
        };
      },
      failNext(message: string) {
        answers.push(() => Promise.reject(new Error(message)));
      },
    };
  }

  it.each(["network", "validation"])(
    "abandons a failed choice returned to its saved value after a %s failure",
    async (failure) => {
      const server = fileServer();
      if (failure === "network") server.failNext("renewal offline");
      else
        save.mockResolvedValueOnce({
          kind: "invalid",
          message: "invalid renewal",
          fieldErrors: { renewal: "renewal refused" },
        });
      await openDefaults();
      const renewal = screen.getByLabelText("Renewal");
      fireEvent.change(renewal, { target: { value: "auto" } });
      fireEvent.blur(renewal);
      await screen.findByText(failure === "network" ? "renewal offline" : "renewal refused");
      fireEvent.change(renewal, { target: { value: "manual" } });
      fireEvent.blur(renewal);
      await waitFor(() =>
        expect(screen.queryByRole("button", { name: "Retry save" })).not.toBeInTheDocument(),
      );
      expect(screen.queryByText("renewal refused")).not.toBeInTheDocument();
      expect(save).toHaveBeenCalledTimes(1);
      server.failNext("shipping offline");
      const shipping = screen.getByLabelText("Shipping profile");
      fireEvent.change(shipping, { target: { value: "Printify EU standard" } });
      fireEvent.blur(shipping);
      await screen.findByText("shipping offline");
      await userEvent.click(screen.getByRole("button", { name: "Retry save" }));
      await screen.findByText("Saved");
      expect(save.mock.calls[2]).toEqual(["r1", { shipping_profile: "Printify EU standard" }]);
      expect(renewal).toHaveValue("manual");
      expect(server.file().listing_defaults.renewal).toBe("manual");
      expect(server.file().listing_defaults.shipping_profile).toBe("Printify EU standard");
    },
  );

  it("abandons failed Custom values when the unchanged POD preset is chosen", async () => {
    const server = fileServer();
    server.failNext("custom offline");
    await openDefaults();
    await userEvent.click(screen.getByRole("radio", { name: /Custom/ }));
    fireEvent.change(screen.getByLabelText("Who made it"), { target: { value: "i_did" } });
    fireEvent.blur(screen.getByLabelText("Who made it"));
    await screen.findByText("custom offline");
    await userEvent.click(screen.getByRole("radio", { name: /Print on demand/ }));
    expect(screen.queryByRole("button", { name: "Retry save" })).not.toBeInTheDocument();
    expect(save).toHaveBeenCalledTimes(1);
    server.failNext("shipping offline");
    fireEvent.change(screen.getByLabelText("Shipping profile"), {
      target: { value: "Printify EU standard" },
    });
    fireEvent.blur(screen.getByLabelText("Shipping profile"));
    await screen.findByText("shipping offline");
    await userEvent.click(screen.getByRole("button", { name: "Retry save" }));
    await screen.findByText("Saved");
    expect(save.mock.calls[2]).toEqual(["r1", { shipping_profile: "Printify EU standard" }]);
    expect(server.file().listing_defaults).toMatchObject({
      who_made: "someone_else",
      when_made: "made_to_order",
      is_supply: false,
    });
  });

  it.each(["network", "validation"])(
    "retains a matching pending draft when a reblurred save has a %s failure",
    async (failure) => {
      const server = fileServer();
      let answer!: (outcome: SaveOutcome) => void;
      let reject!: (error: Error) => void;
      save.mockImplementationOnce(
        () =>
          new Promise((resolve, refuse) => {
            answer = resolve;
            reject = refuse;
          }),
      );
      await openDefaults();
      const renewal = screen.getByLabelText("Renewal");
      fireEvent.change(renewal, { target: { value: "auto" } });
      fireEvent.blur(renewal);
      await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
      renewal.focus();
      fireEvent.blur(renewal);
      await act(async () => {});
      expect(save).toHaveBeenCalledTimes(1);
      await act(async () => {
        if (failure === "network") reject(new Error("renewal offline"));
        else
          answer({
            kind: "invalid",
            message: "invalid renewal",
            fieldErrors: { renewal: "renewal refused" },
          });
      });
      await screen.findByText(failure === "network" ? "renewal offline" : "renewal refused");
      expect(renewal).toHaveValue("auto");
      await userEvent.click(screen.getByRole("button", { name: "Retry save" }));
      await screen.findByText("Saved");
      expect(save.mock.calls[1]).toEqual(["r1", { renewal: "auto" }]);
      expect(server.file().listing_defaults.renewal).toBe("auto");
      expect(renewal).toHaveValue("auto");
    },
  );

  it.each([
    ["renewal", false],
    ["renewal", true],
    ["return_policy", false],
    ["return_policy", true],
  ] as const)(
    "does not reblur a %s value refused by Retry, pending reblur=%s",
    async (field, reblur) => {
      const server = fileServer();
      server.failNext("save offline");
      await openDefaults();
      const control = screen.getByLabelText(field === "renewal" ? "Renewal" : "Return policy");
      const original = (control as HTMLSelectElement).value;
      const value =
        field === "renewal"
          ? "auto"
          : (
              within(control).getByRole("option", {
                name: "returns and exchanges within 14 days",
              }) as HTMLOptionElement
            ).value;
      fireEvent.change(control, { target: { value } });
      fireEvent.blur(control);
      await screen.findByText("save offline");
      let answer!: (outcome: SaveOutcome) => void;
      save.mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            answer = resolve;
          }),
      );
      await userEvent.click(screen.getByRole("button", { name: "Retry save" }));
      await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
      if (reblur) {
        control.focus();
        fireEvent.blur(control);
        await act(async () => {});
      }
      await act(async () =>
        answer({
          kind: "invalid",
          message: "invalid edit",
          fieldErrors: { [field]: "edit refused" },
        }),
      );
      await screen.findByText("edit refused");
      expect(control).toHaveValue(value);
      control.focus();
      fireEvent.blur(control);
      await act(async () => {});
      expect(save).toHaveBeenCalledTimes(2);
      expect(server.file().listing_defaults[field]).toEqual(shop().listing_defaults[field]);

      // A real new edit, including choosing back to the refused value, is
      // allowed to try again. The old field error must not freeze it.
      fireEvent.change(control, { target: { value: original } });
      fireEvent.change(control, { target: { value } });
      fireEvent.blur(control);
      await screen.findByText("Saved");
      const changes: ShopChanges =
        field === "renewal"
          ? { renewal: "auto" }
          : {
              return_policy: { accepts_returns: true, accepts_exchanges: true, within_days: 14 },
            };
      expect(save.mock.calls[2]).toEqual(["r1", changes]);
      expect(server.file().listing_defaults[field]).toEqual(changes[field]);
    },
  );

  it("ignores an abandoned initial Shop read under StrictMode", async () => {
    let release!: (value: ShopSettings) => void;
    vi.mocked(shopApi.getShop).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    render(
      <StrictMode>
        <AdminPage />
      </StrictMode>,
    );
    await userEvent.click(await screen.findByRole("link", { name: "Listing defaults" }));
    const renewal = await screen.findByLabelText("Renewal");
    renewal.focus();
    fireEvent.change(renewal, { target: { value: "auto" } });
    await act(async () => release(shop()));
    expect(screen.getByLabelText("Renewal")).toHaveValue("auto");
    expect(screen.getByLabelText("Renewal")).toHaveFocus();
    expect(save).not.toHaveBeenCalled();
  });

  it.each([false, true])(
    "keeps a sibling's Saved after a cancelled currency failure, queued=%s",
    async (queued) => {
      const server = fileServer();
      const answer = queued ? server.hold() : null;
      await openDefaults();
      fireEvent.change(screen.getByLabelText("Renewal"), { target: { value: "auto" } });
      fireEvent.blur(screen.getByLabelText("Renewal"));
      if (!queued) await screen.findByText("Saved");
      await userEvent.click(screen.getByRole("link", { name: "Connected shops" }));
      await userEvent.click(await screen.findByRole("button", { name: "Change currency…" }));
      const dialog = screen.getByRole("dialog", { name: /converts nothing/ });
      await userEvent.click(within(dialog).getByLabelText(/prices won't be converted/));
      server.failNext("currency offline");
      await userEvent.click(within(dialog).getByRole("button", { name: "Change to EUR" }));
      if (answer) await answer();
      expect(await within(dialog).findByRole("alert")).toHaveTextContent("currency offline");
      await userEvent.click(within(dialog).getByRole("button", { name: "Keep USD" }));
      expect(screen.getByText("Saved")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Retry save" })).not.toBeInTheDocument();
      expect(server.file().listing_defaults.renewal).toBe("auto");
      expect(server.file().currency).toBe("USD");
    },
  );

  it("keeps a newer focused choice when an older save is answered", async () => {
    const server = fileServer();
    const answerAuto = server.hold();
    await openDefaults();
    const renewal = screen.getByLabelText("Renewal");
    renewal.focus();
    fireEvent.change(renewal, { target: { value: "auto" } });
    fireEvent.blur(renewal);
    renewal.focus();
    fireEvent.change(renewal, { target: { value: "manual" } });

    await answerAuto();
    expect(renewal).toHaveValue("manual");
    expect(renewal).toHaveFocus();
    fireEvent.blur(renewal);

    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save.mock.calls[1]).toEqual(["r2", { renewal: "manual" }]);
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(server.file().listing_defaults.renewal).toBe("manual");
    expect(renewal).toHaveValue("manual");
  });

  it("keeps a newer queued choice while the older save is answered", async () => {
    const server = fileServer();
    const answerAuto = server.hold();
    await openDefaults();
    const renewal = screen.getByLabelText("Renewal");
    fireEvent.change(renewal, { target: { value: "auto" } });
    fireEvent.blur(renewal);
    fireEvent.change(renewal, { target: { value: "manual" } });
    fireEvent.blur(renewal);

    await answerAuto();
    expect(renewal).toHaveValue("manual");
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(server.file().listing_defaults.renewal).toBe("manual");
    expect(renewal).toHaveValue("manual");
  });

  it("keeps a failed field unsaved through a sibling's success until it is retried", async () => {
    const server = fileServer();
    server.failNext("network down");
    vi.spyOn(shopApi, "getShop").mockResolvedValue(shop({ who_made: "i_did" }));
    await openDefaults();
    const renewal = screen.getByLabelText("Renewal");
    fireEvent.change(renewal, { target: { value: "auto" } });
    fireEvent.blur(renewal);
    expect(await screen.findByText("network down")).toBeInTheDocument();

    const who = screen.getByLabelText("Who made it");
    fireEvent.change(who, { target: { value: "someone_else" } });
    fireEvent.blur(who);
    await waitFor(() => expect(server.file().listing_defaults.who_made).toBe("someone_else"));
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
    expect(screen.getByText("network down")).toBeInTheDocument();
    expect(renewal).toHaveValue("auto");
    expect(server.file().listing_defaults.renewal).toBe("manual");

    await userEvent.click(screen.getByRole("button", { name: "Retry save" }));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(save.mock.lastCall?.[1]).toEqual({ renewal: "auto" });
    expect(server.file().listing_defaults.renewal).toBe("auto");
    expect(renewal).toHaveValue("auto");
    expect(screen.queryByRole("button", { name: "Retry save" })).not.toBeInTheDocument();
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
  ])("never retries a currency change cancelled with %s after it failed", async (_, cancel) => {
    const server = fileServer();
    server.failNext("network down");
    render(<AdminPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Change currency…" }));
    const dialog = screen.getByRole("dialog", { name: /converts nothing/ });
    await userEvent.click(within(dialog).getByLabelText(/prices won't be converted/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Change to EUR" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("network down");
    await cancel(dialog);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("link", { name: "Listing defaults" }));
    const renewal = screen.getByLabelText("Renewal");
    fireEvent.change(renewal, { target: { value: "auto" } });
    fireEvent.blur(renewal);
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry save" })).not.toBeInTheDocument();
    expect(save.mock.calls.filter(([, changes]) => "currency" in changes)).toHaveLength(1);
    expect(server.file().currency).toBe("USD");
    expect(server.file().listing_defaults.renewal).toBe("auto");
  });

  it("retries a sibling's failure but not a cancelled currency change", async () => {
    const server = fileServer();
    server.failNext("network down");
    await openDefaults();
    const renewal = screen.getByLabelText("Renewal");
    fireEvent.change(renewal, { target: { value: "auto" } });
    fireEvent.blur(renewal);
    expect(await screen.findByText("network down")).toBeInTheDocument();

    server.failNext("still offline");
    await userEvent.click(screen.getByRole("link", { name: "Connected shops" }));
    await userEvent.click(screen.getByRole("button", { name: "Change currency…" }));
    const dialog = screen.getByRole("dialog", { name: /converts nothing/ });
    await userEvent.click(within(dialog).getByLabelText(/prices won't be converted/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Change to EUR" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("still offline");
    await userEvent.click(within(dialog).getByRole("button", { name: "Keep USD" }));

    expect(screen.getByText("network down")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry save" }));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(save.mock.lastCall?.[1]).toEqual({ renewal: "auto" });
    expect(server.file().listing_defaults.renewal).toBe("auto");
    expect(server.file().currency).toBe("USD");
  });

  it("reports Saved when a newer save supersedes a failed one", async () => {
    let fail: ((error: Error) => void) | undefined;
    const server = fileServer();
    save.mockImplementationOnce(() => new Promise<SaveOutcome>((_, reject) => (fail = reject)));
    await openDefaults();
    const renewal = screen.getByLabelText("Renewal");
    fireEvent.change(renewal, { target: { value: "auto" } });
    fireEvent.blur(renewal);
    fireEvent.change(renewal, { target: { value: "manual" } });
    fireEvent.blur(renewal);
    await waitFor(() => expect(fail).toBeDefined());
    await act(async () => fail?.(new Error("network down")));

    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry save" })).not.toBeInTheDocument();
    expect(server.file().listing_defaults.renewal).toBe("manual");
    expect(renewal).toHaveValue("manual");
  });

  async function offerUk() {
    getLookups.mockResolvedValueOnce(lookups({ shipping: ["Printify UK standard"] }));
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    return screen.findByRole("button", { name: "Use it" });
  }

  it("shows what Use it wrote over a draft chosen back to the saved value", async () => {
    const server = fileServer();
    await openDefaults();
    const shipping = screen.getByLabelText("Shipping profile");
    shipping.focus();
    fireEvent.change(shipping, { target: { value: "Printify EU standard" } });
    fireEvent.change(shipping, { target: { value: "Printify US standard" } });
    shipping.blur();
    expect(save).not.toHaveBeenCalled();

    await userEvent.click(await offerUk());
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(server.file().listing_defaults.shipping_profile).toBe("Printify UK standard");
    expect(shipping).toHaveValue("Printify UK standard");

    shipping.focus();
    shipping.blur();
    await act(async () => {});
    expect(save).toHaveBeenCalledTimes(1);
    expect(server.file().listing_defaults.shipping_profile).toBe("Printify UK standard");
  });

  it("shows what Use it wrote over a failed draft", async () => {
    const server = fileServer();
    server.failNext("network down");
    await openDefaults();
    const shipping = screen.getByLabelText("Shipping profile");
    shipping.focus();
    fireEvent.change(shipping, { target: { value: "Printify EU standard" } });
    shipping.blur();
    expect(await screen.findByText("network down")).toBeInTheDocument();

    await userEvent.click(await offerUk());
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(server.file().listing_defaults.shipping_profile).toBe("Printify UK standard");
    expect(shipping).toHaveValue("Printify UK standard");
    expect(screen.queryByRole("button", { name: "Retry save" })).not.toBeInTheDocument();

    shipping.focus();
    shipping.blur();
    await act(async () => {});
    expect(save).toHaveBeenCalledTimes(2);
    expect(server.file().listing_defaults.shipping_profile).toBe("Printify UK standard");
  });

  it("keeps a choice made while Use it is pending and saves it after", async () => {
    const server = fileServer();
    await openDefaults();
    const shipping = screen.getByLabelText("Shipping profile");
    const answerUseIt = server.hold();
    await userEvent.click(await offerUk());
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    shipping.focus();
    fireEvent.change(shipping, { target: { value: "Printify EU standard" } });
    shipping.blur();
    await answerUseIt();

    expect(shipping).toHaveValue("Printify EU standard");
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save.mock.calls[1]).toEqual(["r2", { shipping_profile: "Printify EU standard" }]);
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(server.file().listing_defaults.shipping_profile).toBe("Printify EU standard");
    expect(shipping).toHaveValue("Printify EU standard");
  });

  it("saves a choice made while a retry is pending, after the retry lands", async () => {
    const server = fileServer();
    server.failNext("network down");
    await openDefaults();
    const renewal = screen.getByLabelText("Renewal");
    fireEvent.change(renewal, { target: { value: "auto" } });
    fireEvent.blur(renewal);
    expect(await screen.findByText("network down")).toBeInTheDocument();

    const answerRetry = server.hold();
    await userEvent.click(screen.getByRole("button", { name: "Retry save" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    renewal.focus();
    fireEvent.change(renewal, { target: { value: "manual" } });
    fireEvent.blur(renewal);
    await answerRetry();

    await waitFor(() => expect(save).toHaveBeenCalledTimes(3));
    // The failed request wrote nothing, so the retry's answer is r2.
    expect(save.mock.calls[2]).toEqual(["r2", { renewal: "manual" }]);
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(server.file().listing_defaults.renewal).toBe("manual");
    expect(renewal).toHaveValue("manual");
  });

  it("sends nothing more for a choice that matches the pending retry", async () => {
    const server = fileServer();
    server.failNext("network down");
    await openDefaults();
    const renewal = screen.getByLabelText("Renewal");
    fireEvent.change(renewal, { target: { value: "auto" } });
    fireEvent.blur(renewal);
    expect(await screen.findByText("network down")).toBeInTheDocument();

    const answerRetry = server.hold();
    await userEvent.click(screen.getByRole("button", { name: "Retry save" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    fireEvent.change(renewal, { target: { value: "manual" } });
    fireEvent.change(renewal, { target: { value: "auto" } });
    fireEvent.blur(renewal);
    await answerRetry();

    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(save).toHaveBeenCalledTimes(2);
    expect(server.file().listing_defaults.renewal).toBe("auto");
    expect(renewal).toHaveValue("auto");
  });

  it("adopts a retried save before changing back to the original value", async () => {
    const server = fileServer();
    server.failNext("network down");
    await openDefaults();
    const renewal = screen.getByLabelText("Renewal");
    fireEvent.change(renewal, { target: { value: "auto" } });
    fireEvent.blur(renewal);
    expect(await screen.findByText("network down")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Retry save" }));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(server.file().listing_defaults.renewal).toBe("auto");

    fireEvent.change(renewal, { target: { value: "manual" } });
    fireEvent.blur(renewal);
    await waitFor(() => expect(save).toHaveBeenCalledTimes(3));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(server.file().listing_defaults.renewal).toBe("manual");
  });

  it("keeps a failed retry visible and lets another retry succeed", async () => {
    const server = fileServer();
    server.failNext("network down");
    await openDefaults();
    const renewal = screen.getByLabelText("Renewal");
    fireEvent.change(renewal, { target: { value: "auto" } });
    fireEvent.blur(renewal);
    expect(await screen.findByText("network down")).toBeInTheDocument();

    server.failNext("still offline");
    await userEvent.click(screen.getByRole("button", { name: "Retry save" }));
    expect(await screen.findByText("still offline")).toBeInTheDocument();
    expect(server.file().listing_defaults.renewal).toBe("manual");
    await userEvent.click(screen.getByRole("button", { name: "Retry save" }));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(server.file().listing_defaults.renewal).toBe("auto");
  });

  it("retries a failed unchanged value when its field is left again", async () => {
    const server = fileServer();
    server.failNext("network down");
    await openDefaults();
    const renewal = screen.getByLabelText("Renewal");
    fireEvent.change(renewal, { target: { value: "auto" } });
    fireEvent.blur(renewal);
    expect(await screen.findByText("network down")).toBeInTheDocument();

    renewal.focus();
    fireEvent.blur(renewal);
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(save).toHaveBeenCalledTimes(2);
    expect(server.file().listing_defaults.renewal).toBe("auto");
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
      "https://www.etsy.com/your/shops/me/shop-policies",
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
  });

  it("says briefly why lookups failed and keeps the full reason behind Details", async () => {
    const long =
      "Could not reach Printify: PRINTIFY_API_TOKEN is not set, and is required to read " +
      "Printify's catalog. Put it in C:\\ws\\.env as `PRINTIFY_API_TOKEN=...`.";
    getLookups.mockResolvedValueOnce({
      ...OFFLINE,
      printify: { ...OFFLINE.printify, problem: long },
    });
    await openDefaults();

    const notice = await screen.findByRole("alert");
    expect(notice).toHaveTextContent("Your defaults have not changed.");
    const details = within(notice).getByText("Details").closest("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");
    expect(within(details as HTMLElement).getByText(long)).toBeInTheDocument();
    // Nothing but the disclosure carries the long text.
    const outside = notice.cloneNode(true) as HTMLElement;
    outside.querySelector("details")?.remove();
    expect(outside.textContent).not.toContain("PRINTIFY_API_TOKEN");
  });

  it("retries lookups without saving", async () => {
    getLookups.mockResolvedValueOnce(OFFLINE);
    await openDefaults();
    await screen.findByText(/Could not reach Etsy or Printify/);

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
