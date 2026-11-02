import { WarningOctagonIcon } from "@phosphor-icons/react/dist/csr/WarningOctagon";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { LimitsPanel } from "./_LimitsPanel";

export const meta = {
  title: "6 · Settings — confirm",
  viewport: "laptop",
  description: "Saving new limits: which Marigold templates get their maps refitted, and whether any saved position falls outside.",
};

export default function Frame() {
  return (
    <>
      <LimitsPanel initial={{ smallest: 80, largest: 120, offset: 10, tilt: 15 }} />
      <div className="sa-scrim">
        <div className="sa-modal sp-modal" role="dialog" aria-modal="true" aria-labelledby="tl-confirm">
          <div className="sp-modal__alarm">
            <WarningOctagonIcon size={40} weight="fill" />
            <div>
              <h2 id="tl-confirm">Refit 3 Marigold templates?</h2>
              <p>It runs in the background. You can keep working.</p>
            </div>
            <button type="button" className="sp-modal__close" aria-label="Cancel" data-goto="template-positions-settings/01-limits">
              <XIcon size={16} />
            </button>
          </div>
          <div className="sa-modal__body">
            <ul className="sp-modal__facts">
              <li>
                <strong>Largest: 110% → 120%.</strong> Marigold maps are fitted to cover the largest position
                allowed, so cc1717-folded, cc1717-hanging-on-fence and cc1717-colour-pair are refitted from
                their existing preparation.
              </li>
              <li>
                <strong>Nothing else changes.</strong> Saved positions stay as they are; none fall outside the new
                limits.
              </li>
            </ul>
          </div>
          <div className="sa-modal__foot sd-foot">
            <button type="button" className="btn btn-ghost" data-goto="template-positions-settings/01-limits">
              Keep current limits
            </button>
            <button type="button" className="btn btn-primary" data-goto="template-positions-settings/01-limits">
              Save and refit
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
