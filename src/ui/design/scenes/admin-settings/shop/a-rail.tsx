import type { ReactNode } from "react";
import { LockIcon } from "@phosphor-icons/react/dist/csr/Lock";
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
  title: "A · Ledger rows — Shop",
  viewport: "laptop",
  description: "Direction A, Shop: label-left rows; shop ids and currency are locked rows with a Change… button that starts the check-and-confirm step.",
};

function Locked({ value, label }: { value: string; label: string }) {
  return (
    <div className="adm-locked">
      <LockIcon size={15} className="adm-muted" />
      <span className="adm-locked__value">{value}</span>
      <button type="button" className="btn btn-secondary" aria-label={`Change ${label}`}>
        Change…
      </button>
    </div>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="a-row">
      <div>
        <div className="a-row__label">{label}</div>
        {hint && <div className="a-row__hint">{hint}</div>}
      </div>
      <div className="a-row__control">{children}</div>
    </div>
  );
}

export default function Frame() {
  const l = shop.listing;
  return (
    <>
      <PageHead />
      <div className="adm-body">
        <SectionList active="shop" variant="plain" goto={(s) => `admin-settings/${s}/a-rail`} />
        <div>
          <section className="a-group" aria-labelledby="a-etsy">
            <div className="a-group__head">
              <div>
                <h2 className="a-group__title" id="a-etsy">Etsy shop</h2>
                <p className="a-group__lede">
                  Changing the shop or currency is checked against Etsy first. Listings already deployed stay linked to the
                  shop they were deployed to.
                </p>
              </div>
            </div>
            <Row label="Shop" hint={`Shop id ${shop.etsy.shopId}`}>
              <Locked value={shop.etsy.shopName} label="Etsy shop" />
            </Row>
            <Row label="Currency" hint="Prices in listing files are in this currency.">
              <Locked value={shop.etsy.currency} label="currency" />
            </Row>
          </section>

          <section className="a-group" aria-labelledby="a-defaults">
            <div className="a-group__head">
              <div>
                <h2 className="a-group__title" id="a-defaults">New listing defaults</h2>
                <p className="a-group__lede">What every listing gets on Etsy unless its own file says otherwise.</p>
              </div>
              <SaveStatus state="saved" />
            </div>
            <Row label="Who made it">
              <Select value={l.whoMade} options={whoMadeOptions} label="Who made it" />
            </Row>
            <Row label="When it was made">
              <Select value={l.whenMade} options={whenMadeOptions} label="When it was made" />
            </Row>
            <Row label="Production partner" hint="Required when another company makes the item.">
              <Select value={l.productionPartner} options={productionPartners} label="Production partner" />
            </Row>
            <Row label="Craft supply" hint="Off for finished goods like shirts.">
              <Switch on={l.isSupply} label="Craft supply" />
            </Row>
            <Row label="Renewal">
              <Select value={l.renewal} options={[{ id: "manual", label: "Manual" }, { id: "auto", label: "Automatic" }]} label="Renewal" />
            </Row>
            <Row label="Shipping profile" hint="From your Etsy shop.">
              <Select value={l.shippingProfile} options={shippingProfiles} label="Shipping profile" />
            </Row>
            <Row label="Return policy" hint="From your Etsy shop.">
              <Select value={l.returnPolicy} options={returnPolicies} label="Return policy" />
            </Row>
          </section>

          <section className="a-group" aria-labelledby="a-printify">
            <div className="a-group__head">
              <h2 className="a-group__title" id="a-printify">Printify</h2>
              <SaveStatus state="saved" />
            </div>
            <Row label="Shop" hint={`Shop id ${shop.printify.shopId}`}>
              <Locked value={shop.printify.shopName} label="Printify shop" />
            </Row>
            <Row label="Preferred print provider" hint="Used when a blueprint offers it.">
              <Select value={l.printProvider} options={printProviders} label="Preferred print provider" />
            </Row>
          </section>
        </div>
      </div>
    </>
  );
}
