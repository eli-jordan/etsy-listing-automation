// The Shop tab as one clickable prototype. Every frame on the board mounts it
// with a different starting state; from there everything is live: the section
// list, info cards, the currency modal, the tier switch, the fields, and the
// "Create on Etsy" round trip.
import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { CurrencyCircleDollarIcon } from "@phosphor-icons/react/dist/csr/CurrencyCircleDollar";
import { LinkSimpleIcon } from "@phosphor-icons/react/dist/csr/LinkSimple";
import { LockSimpleIcon } from "@phosphor-icons/react/dist/csr/LockSimple";
import { PrinterIcon } from "@phosphor-icons/react/dist/csr/Printer";
import { SlidersHorizontalIcon } from "@phosphor-icons/react/dist/csr/SlidersHorizontal";
import { SparkleIcon } from "@phosphor-icons/react/dist/csr/Sparkle";
import { StorefrontIcon } from "@phosphor-icons/react/dist/csr/Storefront";
import { WarningOctagonIcon } from "@phosphor-icons/react/dist/csr/WarningOctagon";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useEffect, useRef, useState } from "react";
import {
  counts,
  createLinks,
  currencies,
  defaults,
  etsy,
  podFields,
  printifyShops,
  printProviders,
  productionPartners,
  renewalOptions,
  returnPolicies,
  shippingProfiles,
  supplyOptions,
  tiers,
  whenMadeOptions,
  whoMadeOptions,
  type Tier,
} from "./_fixtures";
import { InfoButton, InfoCard, PageHead, SaveStatus } from "./_parts";
import { SettingsPanel, type Scenario } from "./_settings";

type Section = "connected" | "defaults" | "settings";
type Creatable = "shippingProfile" | "returnPolicy" | "productionPartner" | "printProvider";
type Opt = { id: string; label: string };

export interface ProtoStart {
  scrollTo?: "market";
  section?: Section;
  currencyModal?: boolean;
  tier?: Tier;
  info?: string | null;
  scenario?: Scenario;
}

const asOpts = (xs: string[]): Opt[] => xs.map((x) => ({ id: x, label: x }));

/** What each "Create on …" round trip brings back, as the platform would name it. */
const CREATED: Record<Creatable, string[]> = {
  shippingProfile: ["Printify EU express", "Printify UK standard"],
  returnPolicy: ["Returns and exchanges within 30 days", "Exchanges only, within 14 days"],
  productionPartner: ["Monster Digital", "SwiftPOD"],
  printProvider: ["Printful EU", "Dimona Tee"],
};
const WHERE: Record<Creatable, string> = {
  shippingProfile: "Etsy",
  returnPolicy: "Etsy",
  productionPartner: "Etsy",
  printProvider: "Printify",
};

const currencyName = (id: string) => currencies.find((c) => c.id === id)?.label.split(" · ")[1] ?? id;

export function ShopPrototype({ start = {} }: { start?: ProtoStart }) {
  const [section, setSection] = useState<Section>(start.section ?? "connected");
  const [info, setInfo] = useState<string | null>(start.info ?? null);
  const [currency, setCurrency] = useState(etsy.currency);
  const [modal, setModal] = useState(!!start.currencyModal);
  const [tier, setTier] = useState<Tier>(start.tier ?? "pod");
  const [values, setValues] = useState({
    whoMade: defaults.whoMade,
    whenMade: defaults.whenMade,
    isSupply: "product",
    productionPartner: defaults.productionPartner,
    shippingProfile: defaults.shippingProfile,
    returnPolicy: defaults.returnPolicy,
    renewal: defaults.renewal,
    printProvider: defaults.printProvider,
  });
  const [lists, setLists] = useState<Record<Creatable, Opt[]>>({
    shippingProfile: asOpts(shippingProfiles),
    returnPolicy: asOpts(returnPolicies),
    productionPartner: asOpts(productionPartners),
    printProvider: asOpts(printProviders),
  });
  const [fresh, setFresh] = useState<Partial<Record<Creatable, string>>>({});
  const [away, setAway] = useState<Creatable | null>(null);
  const [save, setSave] = useState<"saved" | "saving">("saved");
  const [offline, setOffline] = useState(start.scenario === "offline");
  const [lookupPending, setLookupPending] = useState(false);
  const lookupTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(lookupTimer.current), []);
  useEffect(() => {
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") { setModal(false); setAway(null); setInfo(null); }
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, []);
  const timer = useRef<number | undefined>(undefined);

  const saved = () => {
    setSave("saving");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setSave("saved"), 700);
  };
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const set = (key: keyof typeof values, v: string) => {
    setValues((s) => ({ ...s, [key]: v }));
    if (key in fresh) setFresh((f) => ({ ...f, [key]: undefined }));
    saved();
  };

  /** The tab regaining focus: re-read the list and call out what is new. */
  const comeBack = () => {
    if (!away) return;
    const field = away;
    const have = new Set(lists[field].map((o) => o.id));
    const next = CREATED[field].find((n) => !have.has(n));
    if (next) {
      setLists((l) => ({ ...l, [field]: [...l[field], { id: next, label: next }] }));
      setFresh((f) => ({ ...f, [field]: next }));
    }
    setAway(null);
  };

  const toggleInfo = (field: string) => setInfo((cur) => (cur === field ? null : field));

  // Clicking anywhere but an info button or card closes the open card.
  const onRootClick = (e: React.MouseEvent) => {
    const t = e.target as HTMLElement;
    if (!t.closest(".s-info-btn") && !t.closest(".s-info")) setInfo(null);
  };

  const Info = (field: string) => (
    <span
      className="sp-info"
      onClick={(e) => {
        if ((e.target as HTMLElement).closest(".s-info-btn")) toggleInfo(field);
      }}
    >
      <InfoButton field={field} open={info === field} />
      {info === field && <InfoCard field={field} variant="popover" style={{ top: 30, left: -12 }} />}
    </span>
  );

  const Label = (label: string, field: string, create?: Creatable) => (
    <span className="sd-label">
      <span className="sd-label__name">
        {label} {Info(field)}
      </span>
      {create && (
        <a
          className="sd-create"
          href={createLinks[create].href}
          onClick={(e) => {
            e.preventDefault();
            setInfo(null);
            setAway(create);
          }}
        >
          {createLinks[create].label} <ArrowSquareOutIcon size={12} weight="bold" />
        </a>
      )}
    </span>
  );

  const Pick = (field: keyof typeof values, label: string, options: Opt[]) => (
    <select className="adm-select" aria-label={label} disabled={offline && ["productionPartner", "printProvider", "shippingProfile", "returnPolicy"].includes(field)} value={values[field]} onChange={(e) => set(field, e.target.value)}>
      {options.map((o) => (
        <option key={o.id} value={o.id}>
          {o.label}
          {fresh[field as Creatable] === o.id ? "  · new" : ""}
        </option>
      ))}
    </select>
  );

  const Fresh = (field: Creatable) =>
    fresh[field] ? (
      <span className="sd-found">
        <SparkleIcon size={13} weight="fill" /> New from {WHERE[field]}: {fresh[field]}
        <button type="button" className="sp-use" onClick={() => set(field, fresh[field]!)}>
          Use it
        </button>
      </span>
    ) : null;

  return (
    <div onClick={onRootClick}>
      <PageHead />
      <div className="adm-body">
        <Nav section={section} onPick={setSection} />
        <div>
          {section === "connected" && connected()}
          {section === "defaults" && listingDefaults()}
          {/* Kept mounted so its state survives a trip to the Shop tab. */}
          <div hidden={section !== "settings"}>
            <SettingsPanel scrollTo={start.scrollTo} scenario={start.scenario} />
          </div>
        </div>
      </div>
      {modal && <CurrencyModal current={currency} onClose={() => setModal(false)} onConfirm={(c) => {
        setCurrency(c);
        setModal(false);
        saved();
      }} />}
      {away && <AwayBanner where={WHERE[away]} what={labelOf(away)} onBack={comeBack} onCancel={() => setAway(null)} />}
    </div>
  );

  function connected() {
    const printify = printifyShops.find((s) => s.current)!;
    return (
      <section className="b-panel" aria-labelledby="sp-conn">
        <div className="b-panel__head">
          <div>
            <h2 className="b-panel__title" id="sp-conn">Connected shops</h2>
            <p className="b-panel__lede">
              Listings are created in Printify and published to Etsy. Both shops come from the accounts you signed in
              with, so they can't be changed here.
            </p>
          </div>
          <SaveStatus state={save} />
        </div>
        <div className="sa-table">
          <div className="sa-row">
            <StorefrontIcon size={18} />
            <span className="sa-row__label">
              Etsy shop {Info("etsyShop")}
            </span>
            <span className="sa-row__value">
              {start.scenario === "disconnected" ? <>
                <strong>Not connected</strong>
                <span className="sd-sub sp-connect-command">Sign in, then configure this workspace.<code>etsy-listings auth etsy</code><code>etsy-listings setup</code></span>
              </> : <>
                <strong>{etsy.shopName}</strong> <span className="s-muted s-mono">#{etsy.shopId}</span>
                <span className="sd-sub">Signed in as {etsy.account}</span>
              </>}
            </span>
            <span className="sd-readonly">
              <LockSimpleIcon size={12} /> Read-only
            </span>
          </div>
          <div className="sa-row">
            <PrinterIcon size={18} />
            <span className="sa-row__label">
              Printify shop {Info("printifyShop")}
            </span>
            <span className="sa-row__value">
              {start.scenario === "disconnected" ? <>
                <strong>Not connected</strong>
                <span className="sd-sub sp-connect-command">Connect, then configure this workspace.<code>etsy-listings auth printify</code><code>etsy-listings setup</code></span>
              </> : <>
                <strong>{printify.title}</strong> <span className="s-muted s-mono">#{printify.id}</span>
                <span className="sd-sub">
                  <LinkSimpleIcon size={12} weight="bold" /> Publishes to {etsy.shopName}
                </span>
              </>}
            </span>
            <span className="sd-readonly">
              <LockSimpleIcon size={12} /> Read-only
            </span>
          </div>
        </div>

        <div style={{ marginTop: "var(--space-6)" }}>
          <h3 className="sa-danger__title">
            <WarningOctagonIcon size={18} weight="bold" /> Danger zone
          </h3>
          <div className="sa-danger" style={{ marginTop: 0 }}>
            <div className="sa-danger__row">
              <div>
                <p className="sa-danger__name" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <CurrencyCircleDollarIcon size={16} /> Currency: {currency} · {currencyName(currency)}
                  {Info("currency")}
                </p>
                <p className="sa-danger__desc">
                  Prices in listing files are read in this currency. Changing it converts nothing, and listings already
                  on Etsy keep their currency.
                </p>
              </div>
              <button type="button" className="btn btn-danger-outline" onClick={() => setModal(true)}>
                Change currency…
              </button>
            </div>
          </div>
        </div>
      </section>
    );
  }

  function listingDefaults() {
    return (
      <section className="b-panel" aria-labelledby="sp-defaults">
        <div className="b-panel__head">
          <div>
            <h2 className="b-panel__title" id="sp-defaults">Listing defaults</h2>
            <p className="b-panel__lede">What every listing is set up with on Etsy, unless its own file says otherwise.</p>
          </div>
          <SaveStatus state={save} />
        </div>

        <span className="sd-label__name" style={{ fontSize: 13, fontWeight: 600 }}>
          How your items are made {Info("tier")}
        </span>
        <div className="sa-tiers" role="radiogroup" aria-label="How your items are made">
          {tiers.map((t) => (
            <button
              key={t.id}
              type="button"
              role="radio"
              aria-checked={t.id === tier}
              className={t.id === tier ? "sa-tier is-on" : "sa-tier"}
              onClick={() => {
                if (t.id !== tier) {
                  setTier(t.id);
                  saved();
                }
              }}
            >
              <span className={t.id === tier ? "sa-radio is-on" : "sa-radio"} />
              {t.label}
              {t.recommended && <span className="sa-reco">Recommended</span>}
            </button>
          ))}
        </div>

        {tier === "pod" ? (
          <dl className="sd-set" aria-label="What Print on demand sets">
            {podFields.map((f) => (
              <div key={f.key} className="sd-set__row">
                <dt>
                  <span className="sd-label__name">
                    {f.label} {Info(f.key)}
                  </span>
                </dt>
                <dd>{f.value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <div className="sa-fields sd-custom sd-custom--3">
            <div className="sa-field">
              {Label("Who made it", "whoMade")}
              {Pick("whoMade", "Who made it", whoMadeOptions)}
            </div>
            <div className="sa-field">
              {Label("When it was made", "whenMade")}
              {Pick("whenMade", "When it was made", whenMadeOptions)}
            </div>
            <div className="sa-field">
              {Label("What it is", "isSupply")}
              {Pick("isSupply", "What it is", supplyOptions)}
            </div>
          </div>
        )}

        <h3 className="sa-subhead">Fulfilment and policies</h3>
        <div className="sp-discovery">
          <span role="status">{lookupPending ? "Refreshing Etsy and Printify lists…" : offline ? "Could not reach Etsy or Printify. Saved choices are shown." : "Lists refresh when you return to this window."}</span>
          <button type="button" className="btn btn-ghost" disabled={lookupPending} onClick={() => {
            setLookupPending(true);
            lookupTimer.current = window.setTimeout(() => { setOffline(false); setLookupPending(false); }, 800);
          }}>{lookupPending ? "Refreshing…" : offline ? "Retry lookups" : "Refresh lists"}</button>
        </div>
        {offline && <div className="adm-warn sp-notice" role="alert"><WarningOctagonIcon size={18} /><span>Your defaults have not changed. Retry to load available choices. You can still edit renewal and how your items are made.</span></div>}
        <div className="sa-fields">
          <div className="sa-field">
            {Label("Production partner", "productionPartner", "productionPartner")}
            {Pick("productionPartner", "Production partner", lists.productionPartner)}
            {Fresh("productionPartner")}
          </div>
          <div className="sa-field">
            {Label("Preferred print provider", "printProvider", "printProvider")}
            {Pick("printProvider", "Preferred print provider", lists.printProvider)}
            {Fresh("printProvider")}
          </div>
          <div className="sa-field">
            {Label("Shipping profile", "shippingProfile", "shippingProfile")}
            {Pick("shippingProfile", "Shipping profile", lists.shippingProfile)}
            {Fresh("shippingProfile")}
          </div>
          <div className="sa-field">
            {Label("Return policy", "returnPolicy", "returnPolicy")}
            {Pick("returnPolicy", "Return policy", lists.returnPolicy)}
            {Fresh("returnPolicy")}
          </div>
          <div className="sa-field">
            {Label("Renewal", "renewal")}
            {Pick("renewal", "Renewal", renewalOptions)}
          </div>
        </div>
        <p className="sd-refresh">Made something new on Etsy or Printify? The lists refresh when you come back to this tab.</p>
      </section>
    );
  }
}

function labelOf(f: Creatable) {
  return {
    shippingProfile: "a shipping profile",
    returnPolicy: "a return policy",
    productionPartner: "a production partner",
    printProvider: "a print provider",
  }[f];
}

function Nav({ section, onPick }: { section: Section; onPick: (s: Section) => void }) {
  const sub: { id: Section; label: string }[] = [
    { id: "connected", label: "Connected shops" },
    { id: "defaults", label: "Listing defaults" },
  ];
  return (
    <nav className="adm-sections adm-sections--described" aria-label="Admin sections">
      <a
        href="#shop"
        className={section === "settings" ? "adm-sections__item" : "adm-sections__item adm-sections__item--active"}
        onClick={(e) => {
          e.preventDefault();
          onPick("connected");
        }}
      >
        <span className="adm-sections__icon">
          <StorefrontIcon size={18} />
        </span>
        <span className="adm-sections__text">
          <span className="adm-sections__label">Shop</span>
          <span className="adm-sections__hint">shop.yaml</span>
        </span>
      </a>
      <div className="s-subnav">
        {sub.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            className={s.id === section ? "s-subnav__item is-active" : "s-subnav__item"}
            aria-current={s.id === section ? "page" : undefined}
            onClick={(e) => {
              e.preventDefault();
              onPick(s.id);
            }}
          >
            {s.label}
          </a>
        ))}
      </div>
      <a
        href="#settings"
        className={section === "settings" ? "adm-sections__item adm-sections__item--active" : "adm-sections__item"}
        aria-current={section === "settings" ? "page" : undefined}
        onClick={(e) => {
          e.preventDefault();
          onPick("settings");
        }}
      >
        <span className="adm-sections__icon">
          <SlidersHorizontalIcon size={18} />
        </span>
        <span className="adm-sections__text">
          <span className="adm-sections__label">Settings</span>
          <span className="adm-sections__hint">settings.yaml</span>
        </span>
      </a>
    </nav>
  );
}

function CurrencyModal({
  current,
  onClose,
  onConfirm,
}: {
  current: string;
  onClose: () => void;
  onConfirm: (c: string) => void;
}) {
  const [next, setNext] = useState(currencies.find((c) => c.id !== current)!.id);
  const [ack, setAck] = useState(false);
  const sample = new Intl.NumberFormat("en", { style: "currency", currency: next }).format(24.99);
  return (
    <div className="sa-scrim" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sa-modal sp-modal" role="dialog" aria-modal="true" aria-labelledby="sp-cur-title">
        <div className="sp-modal__alarm">
          <WarningOctagonIcon size={40} weight="fill" />
          <div>
            <h2 id="sp-cur-title">Changing currency converts nothing</h2>
            <p>Read this before you change it. It can't be undone automatically.</p>
          </div>
          <button type="button" className="sp-modal__close" aria-label="Cancel" onClick={onClose}>
            <XIcon size={16} />
          </button>
        </div>
        <div className="sa-modal__body">
          <ul className="sp-modal__facts">
            <li>
              <strong>No conversion.</strong> 24.99 in a listing file is read as <strong>{sample}</strong>. Re-price your
              listing files yourself.
            </li>
            <li>
              <strong>Existing listings stay as they are.</strong> The {counts.deployed} listings already on Etsy keep
              their {current} prices.
            </li>
            {next !== etsy.currency && <li>
              <strong>Your Etsy shop sells in {etsy.currency}.</strong> A different currency here no longer matches it.
            </li>}
          </ul>
          <label className="sd-modal-label" htmlFor="sp-cur">
            New currency
          </label>
          <select id="sp-cur" className="adm-select" value={next} onChange={(e) => setNext(e.target.value)}>
            {currencies
              .filter((c) => c.id !== current)
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
          </select>
          <label className="sp-ack">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            <span className={ack ? "sb-box is-on" : "sb-box"} aria-hidden="true">
              {ack && <CheckIcon size={12} weight="bold" />}
            </span>
            I understand prices won't be converted
          </label>
        </div>
        <div className="sa-modal__foot sd-foot">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Keep {current}
          </button>
          <button type="button" className="btn btn-danger" disabled={!ack} onClick={() => onConfirm(next)}>
            Change to {next}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Stands in for the other browser tab: in the app this is just the window regaining focus. */
function AwayBanner({
  where,
  what,
  onBack,
  onCancel,
}: {
  where: string;
  what: string;
  onBack: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="sa-scrim sp-away">
      <div className="sp-away__card" role="dialog" aria-modal="true" aria-labelledby="sp-away-title">
        <p className="sp-away__kicker">Prototype · stands in for the {where} tab</p>
        <h2 id="sp-away-title">
          {where} opened in a new tab
        </h2>
        <p>Create {what} there, then come back. The list refreshes as soon as this tab has focus again.</p>
        <div className="sd-foot">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Came back without creating
          </button>
          <button type="button" className="btn btn-primary" onClick={onBack}>
            Come back with a new one
          </button>
        </div>
      </div>
    </div>
  );
}
