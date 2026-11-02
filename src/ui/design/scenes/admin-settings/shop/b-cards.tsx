import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { LockIcon } from "@phosphor-icons/react/dist/csr/Lock";
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
  title: "B · Panels — Shop",
  viewport: "laptop",
  description:
    "Direction B, Shop: Etsy and Printify panels; changing the Printify shop opens an inline check-and-confirm block inside the panel.",
};

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="b-field">
      <label>{label}</label>
      {children}
      {hint && <div className="b-field__hint">{hint}</div>}
    </div>
  );
}

function Locked({ value, sub, label }: { value: string; sub: string; label: string }) {
  return (
    <div className="adm-locked">
      <LockIcon size={15} className="adm-muted" />
      <span>
        <span className="adm-locked__value">{value}</span>
        <span className="adm-muted" style={{ fontSize: 12.5, marginLeft: 8 }}>{sub}</span>
      </span>
      <span style={{ flex: 1 }} />
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
      <div className="adm-body">
        <SectionList active="shop" variant="described" goto={(s) => `admin-settings/${s}/b-cards`} />
        <div>
          <section className="b-panel" aria-labelledby="b-etsy">
            <div className="b-panel__head">
              <div>
                <h2 className="b-panel__title" id="b-etsy">Etsy</h2>
                <p className="b-panel__lede">The shop listings deploy to, and what each new listing is set up with.</p>
              </div>
              <SaveStatus state="saved" />
            </div>
            <div className="b-form">
              <Field label="Shop">
                <Locked value={shop.etsy.shopName} sub={`#${shop.etsy.shopId}`} label="Etsy shop" />
              </Field>
              <Field label="Currency">
                <Locked value={shop.etsy.currency} sub="US dollar" label="currency" />
              </Field>
              <Field label="Who made it">
                <Select value={l.whoMade} options={whoMadeOptions} label="Who made it" />
              </Field>
              <Field label="Production partner" hint="Required because another company makes the item.">
                <Select value={l.productionPartner} options={productionPartners} label="Production partner" />
              </Field>
              <Field label="When it was made">
                <Select value={l.whenMade} options={whenMadeOptions} label="When it was made" />
              </Field>
              <Field label="Renewal">
                <Select value={l.renewal} options={[{ id: "manual", label: "Manual" }, { id: "auto", label: "Automatic" }]} label="Renewal" />
              </Field>
              <Field label="Shipping profile" hint="Fetched from your Etsy shop.">
                <Select value={l.shippingProfile} options={shippingProfiles} label="Shipping profile" />
              </Field>
              <Field label="Return policy" hint="Fetched from your Etsy shop.">
                <Select value={l.returnPolicy} options={returnPolicies} label="Return policy" />
              </Field>
              <Field label="Craft supply">
                <span className="b-check">
                  <Switch on={l.isSupply} label="Craft supply" /> Not a craft supply
                </span>
              </Field>
            </div>
          </section>

          <section className="b-panel" aria-labelledby="b-printify">
            <div className="b-panel__head">
              <div>
                <h2 className="b-panel__title" id="b-printify">Printify</h2>
                <p className="b-panel__lede">Where products are created before they are published to Etsy.</p>
              </div>
            </div>
            <div className="b-form">
              <Field label="Shop">
                <Select value="19902455" options={[{ id: "19884321", label: "NaturallyInked on Etsy" }, { id: "19902455", label: "NaturallyInked Test" }]} label="Printify shop" />
              </Field>
              <Field label="Preferred print provider" hint="Used when a blueprint offers it.">
                <Select value={l.printProvider} options={printProviders} label="Preferred print provider" />
              </Field>
              <div className="b-verify" role="group" aria-labelledby="b-verify-title">
                <p className="b-verify__title" id="b-verify-title">Switch Printify shop to NaturallyInked Test?</p>
                <span className="b-verify__ok">
                  <CheckCircleIcon size={15} /> Your Printify token can reach this shop.
                </span>
                <ul className="b-verify__list">
                  <li>New listings will create products in NaturallyInked Test.</li>
                  <li>14 deployed listings stay linked to products in NaturallyInked on Etsy.</li>
                  <li>Nothing changes on Printify until you deploy.</li>
                </ul>
                <div className="b-verify__actions">
                  <button type="button" className="btn btn-primary">Switch shop</button>
                  <button type="button" className="btn btn-ghost">Keep NaturallyInked on Etsy</button>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
