import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { useEffect, useRef, useState } from "react";
import type { ShopSettings } from "../../api/shop";
import { AlarmDialog } from "./AlarmDialog";

export function CurrencyDialog({
  current,
  currencies,
  etsyShopCurrency,
  onCancel,
  onConfirm,
}: {
  current: string;
  currencies: ShopSettings["supported_currencies"];
  etsyShopCurrency: string | null;
  onCancel: () => void;
  /** The refusal to show, or null once saved. */
  onConfirm: (code: string) => Promise<string | null>;
}) {
  const offered = currencies.filter((c) => c.code !== current);
  const [next, setNext] = useState(offered[0]?.code ?? current);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const select = useRef<HTMLSelectElement>(null);

  useEffect(() => select.current?.focus(), []);

  const confirm = async () => {
    setBusy(true);
    setError(null);
    const failure = await onConfirm(next).catch((reason: unknown) =>
      reason instanceof Error ? reason.message : "could not save shop.yaml",
    );
    if (failure !== null) {
      setError(failure);
      setBusy(false);
    }
  };

  return (
    <AlarmDialog
      titleId="sp-cur-title"
      title="Changing currency converts nothing"
      lede="Read this before you change it. It can't be undone automatically."
      onCancel={onCancel}
    >
      <div className="sa-modal__body">
        <ul className="sp-modal__facts">
          <li>
            <strong>No conversion.</strong> Prices saved in listing files keep the currency written
            beside them. Re-price them in {next} yourself; a listing still priced in {current} may
            not deploy until you do.
          </li>
          <li>
            <strong>Existing listings stay as they are.</strong> Listings already on Etsy keep their
            prices, and Etsy's own shop currency does not change.
          </li>
          {etsyShopCurrency !== null && next !== etsyShopCurrency && (
            <li>
              <strong>Your Etsy shop sells in {etsyShopCurrency}.</strong> A different currency here
              no longer matches it.
            </li>
          )}
        </ul>
        <label className="sd-modal-label" htmlFor="sp-cur">
          New currency
        </label>
        <select
          ref={select}
          id="sp-cur"
          className="adm-select"
          value={next}
          onChange={(e) => setNext(e.target.value)}
        >
          {offered.map((c) => (
            <option key={c.code} value={c.code}>
              {c.code} · {c.name}
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
        {error !== null && (
          <p className="adm-error-text" role="alert">
            {error}
          </p>
        )}
      </div>
      <div className="sa-modal__foot sd-foot">
        <button type="button" className="btn btn-ghost" onClick={onCancel}>
          Keep {current}
        </button>
        <button
          type="button"
          className="btn btn-danger"
          disabled={!ack || busy}
          onClick={() => void confirm()}
        >
          Change to {next}
        </button>
      </div>
    </AlarmDialog>
  );
}
