import { CurrencyCircleDollarIcon } from "@phosphor-icons/react/dist/csr/CurrencyCircleDollar";
import { LinkSimpleIcon } from "@phosphor-icons/react/dist/csr/LinkSimple";
import { LockSimpleIcon } from "@phosphor-icons/react/dist/csr/LockSimple";
import { PrinterIcon } from "@phosphor-icons/react/dist/csr/Printer";
import { StorefrontIcon } from "@phosphor-icons/react/dist/csr/Storefront";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { WarningOctagonIcon } from "@phosphor-icons/react/dist/csr/WarningOctagon";
import type { ReactNode, Ref } from "react";
import type { ConnectionRow, ShopConnections, ShopSettings } from "../../api/shop";
import { Info, type InfoState } from "./Info";

/**
 * Read-only identities and the currency danger zone (interactions,
 * *Connected shops and currency*). Names and ids are text, not disabled
 * pickers; a missing connection names the command to run, and a failed
 * lookup keeps the configured identity beside its problem.
 */
export function ConnectedShops({
  shop,
  connections,
  connectionsError,
  info,
  locked,
  currencyButton,
  onChangeCurrency,
}: {
  shop: ShopSettings | null;
  connections: ShopConnections | null;
  connectionsError: string | null;
  info: InfoState;
  locked: boolean;
  currencyButton: Ref<HTMLButtonElement>;
  onChangeCurrency: () => void;
}) {
  const currencyName =
    shop?.supported_currencies.find((c) => c.code === shop.currency)?.name ?? null;
  return (
    <section className="b-panel" aria-labelledby="sp-conn">
      <div className="b-panel__head">
        <div>
          <h2 className="b-panel__title" id="sp-conn">
            Connected shops
          </h2>
          <p className="b-panel__lede">
            Listings are created in Printify and published to Etsy. Both shops come from the
            accounts you signed in with, so they can't be changed here.
          </p>
        </div>
      </div>
      {connectionsError !== null && (
        <p className="adm-error-text" role="alert">
          {connectionsError}
        </p>
      )}
      <div className="sa-table">
        <Row
          testId="connection-etsy"
          icon={<StorefrontIcon size={18} />}
          label="Etsy shop"
          field="etsyShop"
          info={info}
          row={connections?.etsy ?? null}
          connected={(row) =>
            row.signed_in_user_id !== null
              ? `Signed in as Etsy user #${row.signed_in_user_id}`
              : null
          }
          missing="Sign in, then configure this workspace."
        />
        <Row
          testId="connection-printify"
          icon={<PrinterIcon size={18} />}
          label="Printify shop"
          field="printifyShop"
          info={info}
          row={connections?.printify ?? null}
          connected={(row) =>
            row.sales_channel === "etsy" ? (
              <>
                <LinkSimpleIcon size={12} weight="bold" /> Connected to Etsy
              </>
            ) : (
              "Not connected to a sales channel"
            )
          }
          missing="Connect, then configure this workspace."
        />
      </div>

      <div className="sp-danger-zone">
        <h3 className="sa-danger__title">
          <WarningOctagonIcon size={18} weight="bold" /> Danger zone
        </h3>
        <div className="sa-danger">
          <div className="sa-danger__row">
            <div>
              <p className="sa-danger__name sp-danger-name">
                <CurrencyCircleDollarIcon size={16} /> Currency:{" "}
                {shop ? `${shop.currency}${currencyName ? ` · ${currencyName}` : ""}` : "…"}
                <Info field="currency" info={info} />
              </p>
              <p className="sa-danger__desc">
                Every price in this workspace is written in this currency. Changing it converts
                nothing: saved prices keep their currency, and listings already on Etsy keep theirs.
              </p>
            </div>
            <button
              ref={currencyButton}
              type="button"
              className="btn btn-danger-outline"
              disabled={!shop || locked}
              onClick={onChangeCurrency}
            >
              Change currency…
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

function Row({
  testId,
  icon,
  label,
  field,
  info,
  row,
  connected,
  missing,
}: {
  testId: string;
  icon: ReactNode;
  label: string;
  field: string;
  info: InfoState;
  row: ConnectionRow | null;
  connected: (row: ConnectionRow) => ReactNode;
  missing: string;
}) {
  return (
    <div className="sa-row" data-testid={testId}>
      {icon}
      <span className="sa-row__label">
        {label} <Info field={field} info={info} />
      </span>
      <span className="sa-row__value">
        {row === null ? (
          <span className="s-muted">Checking…</span>
        ) : row.state === "not_connected" ? (
          <>
            <strong>Not connected</strong>
            <span className="sd-sub sp-connect-command">
              {row.commands.includes("etsy-listings setup") && row.commands.length > 1
                ? missing
                : row.commands.includes("etsy-listings setup")
                  ? "Configure this workspace."
                  : "Sign in again to use this shop."}
              {row.commands.map((command) => (
                <code key={command}>{command}</code>
              ))}
            </span>
          </>
        ) : (
          <>
            <strong>{row.shop_name ?? "Unnamed shop"}</strong>{" "}
            {row.shop_id !== null && <span className="s-muted s-mono">#{row.shop_id}</span>}
            {row.state === "lookup_failed" ? (
              <span className="sd-sub sp-lookup-problem">
                <WarningIcon size={12} weight="bold" /> {row.problem}
              </span>
            ) : (
              <span className="sd-sub">{connected(row)}</span>
            )}
          </>
        )}
      </span>
      <span className="sd-readonly">
        <LockSimpleIcon size={12} /> Read-only
      </span>
    </div>
  );
}
