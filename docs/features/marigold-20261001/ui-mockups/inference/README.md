# Custom inference settings

Archived comparison: option C was selected and integrated into the full workflow, with its launcher inside the Marigold Renderer section and matching field/card labels. No preset selector. Only `num_inference_steps` and `ensemble_size` are exposed, defaulting to the prototype ensemble settings of **10** and **3**. Resolution and seed remain internal and are absent from the UI. Reset to defaults restores both exposed values.

- [A: Inline Advanced panel](a-inline.png) — a compact inspector section with a contextual information card. Clicking a field's information icon changes the card.
- [B: Side drawer](b-drawer.png) — each setting has its own explanation card, with Reset and Save in the footer.
- [C: Dialog](c-dialog.png) — controls on the left and documentation-linked reference cards on the right.

Information cards link to the official [Marigold guide](https://huggingface.co/docs/diffusers/main/using-diffusers/marigold_usage). Settings changes apply on the next explicit template preparation. These are local mock interactions and do not start model inference or persist settings. The final labels are Inference steps and Ensemble size. See the [integrated dialog](../inference-settings.png).
