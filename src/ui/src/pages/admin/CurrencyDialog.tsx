import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { WarningOctagonIcon } from "@phosphor-icons/react/dist/csr/WarningOctagon";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useEffect, useRef, useState } from "react";
import type { ShopSettings } from "../../api/shop";

/**
 * The currency danger zone's warning (interactions, *Connected shops and
 * currency*). Opening it writes nothing; Change stays disabled until the
 * acknowledgement is ticked, which starts unticked every time. Keep, the
 * close button, Escape and the backdrop all cancel. Focus stays inside.
 *
 * The copy is the production correction of the prototype's: a saved price
 * keeps the currency written beside it (ADR-0006, ADR-0019); it is never
 * reread in the new currency.
 */
export function CurrencyDialog({
  current,
  currencies,
  shopCurrency,
  onCancel,
  onConfirm,
}: {
  current: string;
  currencies: ShopSettings["supported_currencies"];
  /** What the live Etsy shop sells in, when a lookup read it. */
  shopCurrency: string | null;
  onCancel: () => void;
  /** Resolves once saved; rejects with the reason to show. */
  onConfirm: (code: string) => Promise<void>;
}) {
  const offered = currencies.filter((c) => c.code !== current);
  const [next, setNext] = useState(offered[0]?.code ?? current);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const select = useRef<HTMLSelectElement>(null);

  useEffect(() => select.current?.focus(), []);
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== "Tab" || !dialog.current) return;
      const focusable = [
        ...dialog.current.querySelectorAll<HTMLElement>("button, select, input, a[href]"),
      ].filter((el) => !el.hasAttribute("disabled"));
      if (focusable.length === 0) return;
      const at = focusable.indexOf(document.activeElement as HTMLElement);
      const next =
        at < 0
          ? event.shiftKey
            ? focusable.length - 1
            : 0
          : (at + (event.shiftKey ? -1 : 1) + focusable.length) % focusable.length;
      event.preventDefault();
      focusable[next]?.focus();
    };
    // Clicking non-focusable modal content can leave focus on body. Capture
    // Tab on window so the next key still stays inside the dialog.
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onCancel]);

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "could not save shop.yaml");
      setBusy(false);
    }
  };

  return (
    <div className="sa-scrim" onClick={(e) => e.target === e.currentTarget && onCancel()}>
      <div
        ref={dialog}
        className="sa-modal sp-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="sp-cur-title"
      >
        <div className="sp-modal__alarm">
          <WarningOctagonIcon size={40} weight="fill" />
          <div>
            <h2 id="sp-cur-title">Changing currency converts nothing</h2>
            <p>Read this before you change it. It can't be undone automatically.</p>
          </div>
          <button type="button" className="sp-modal__close" aria-label="Cancel" onClick={onCancel}>
            <XIcon size={16} />
          </button>
        </div>
        <div className="sa-modal__body">
          <ul className="sp-modal__facts">
            <li>
              <strong>No conversion.</strong> Prices saved in listing files keep the currency
              written beside them. Re-price them in {next} yourself; a listing still priced in{" "}
              {current} may not deploy until you do.
            </li>
            <li>
              <strong>Existing listings stay as they are.</strong> Listings already on Etsy keep
              their prices, and Etsy's own shop currency does not change.
            </li>
            {shopCurrency !== null && next !== shopCurrency && (
              <li>
                <strong>Your Etsy shop sells in {shopCurrency}.</strong> A different currency here
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
      </div>
    </div>
  );
}
