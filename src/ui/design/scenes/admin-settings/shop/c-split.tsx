import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import type { ReactNode } from "react";
import {
  printProviders,
  productionPartners,
  returnPolicies,
  shippingProfiles,
  shop,
  whenMadeOptions,
  whoMadeOptions,
} from "../_fixtures";
import { PageHead, SaveStatus, SectionList, Select, Switch } from "../_parts";

export const meta = {
  title: "C · Form + explanation — Shop",
  viewport: "laptop",
  description:
    "Direction C, Shop: guarded values as compact rows with Change…; the right column summarises a new listing; shown with the currency confirm dialog open.",
};

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="c-field">
      <label>{label}</label>
      {children}
      {hint && <div className="c-field__hint">{hint}</div>}
    </div>
  );
}

function Guard({ label, value }: { label: string; value: string }) {
  return (
    <div className="c-guard">
      <span>
        <span className="c-guard__label">{label}</span>
        <br />
        <span className="c-guard__value">{value}</span>
      </span>
      <button type="button" className="btn btn-secondary" aria-label={`Change ${label}`}>
        Change…
      </button>
    </div>
  );
}

export default function Frame() {
  const l = shop.listing;
  return (
    <>
      <PageHead />
      <div className="c-body">
        <SectionList active="shop" variant="compact" goto={(s) => `admin-settings/${s}/c-split`} />

        <div className="c-form">
          <section aria-labelledby="c-accounts">
            <h2 className="c-block__title" id="c-accounts">Connected shops</h2>
            <p className="c-block__lede">Checked against Etsy or Printify before they change.</p>
            <Guard label="Etsy shop" value={`${shop.etsy.shopName} · #${shop.etsy.shopId}`} />
            <Guard label="Currency" value={shop.etsy.currency} />
            <Guard label="Printify shop" value={`${shop.printify.shopName} · #${shop.printify.shopId}`} />
          </section>

          <section aria-labelledby="c-new">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <h2 className="c-block__title" id="c-new">New listing defaults</h2>
              <SaveStatus state="saved" />
            </div>
            <p className="c-block__lede">Applied on Etsy unless a listing's own file says otherwise.</p>
            <div className="c-pair">
              <Field label="Who made it">
                <Select value={l.whoMade} options={whoMadeOptions} label="Who made it" />
              </Field>
              <Field label="Production partner">
                <Select value={l.productionPartner} options={productionPartners} label="Production partner" />
              </Field>
              <Field label="When it was made">
                <Select value={l.whenMade} options={whenMadeOptions} label="When it was made" />
              </Field>
              <Field label="Renewal">
                <Select value={l.renewal} options={[{ id: "manual", label: "Manual" }, { id: "auto", label: "Automatic" }]} label="Renewal" />
              </Field>
              <Field label="Shipping profile">
                <Select value={l.shippingProfile} options={shippingProfiles} label="Shipping profile" />
              </Field>
              <Field label="Return policy">
                <Select value={l.returnPolicy} options={returnPolicies} label="Return policy" />
              </Field>
              <Field label="Preferred print provider">
                <Select value={l.printProvider} options={printProviders} label="Preferred print provider" />
              </Field>
              <Field label="Craft supply">
                <span className="b-check">
                  <Switch on={l.isSupply} label="Craft supply" /> No
                </span>
              </Field>
            </div>
          </section>
        </div>

        <aside className="c-aside" aria-label="How a new listing is set up">
          <div className="c-explain">
            <h3 className="c-explain__title">A new listing on Etsy</h3>
            <dl className="c-sum">
              <dt>Shop</dt>
              <dd>{shop.etsy.shopName}</dd>
              <dt>Made by</dt>
              <dd>Printify, to order</dd>
              <dt>Ships with</dt>
              <dd>{l.shippingProfile}</dd>
              <dt>Returns</dt>
              <dd>{l.returnPolicy}</dd>
              <dt>Renews</dt>
              <dd>Manually</dd>
              <dt>Printed by</dt>
              <dd>{l.printProvider}, if offered</dd>
            </dl>
          </div>
        </aside>
      </div>

      <div className="c-scrim">
        <div className="c-dialog" role="dialog" aria-modal="true" aria-labelledby="c-dlg-title">
          <h2 id="c-dlg-title">Change currency to EUR?</h2>
          <span className="b-verify__ok">
            <CheckCircleIcon size={15} /> Etsy confirms {shop.etsy.shopName} accepts EUR.
          </span>
          <ul>
            <li>Prices in your listing files will be read as euros from now on. They are not converted.</li>
            <li>Listings already on Etsy keep their prices until you deploy them again.</li>
          </ul>
          <div className="c-dialog__actions">
            <button type="button" className="btn btn-ghost">Keep USD</button>
            <button type="button" className="btn btn-primary">Change to EUR</button>
          </div>
        </div>
      </div>
    </>
  );
}
