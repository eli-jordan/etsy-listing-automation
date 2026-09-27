### Built from the real editor

These frames mount the app's own **VariantsTab, PricingTab, ImagesTab, EditableName** and save line over a fixture API (`_mockApi.ts`). Nothing is a lookalike.

**Changes the real components need for templates**

- **DesignSelect**: preview wording (*Preview design…*, *Only for previewing…*) and a preview-design list.
- **MediaLocator**: the Files group label *This listing* becomes *This template*.
- **IssuesBanner**: a template wording (*to fix before this template saves*), with no *Prevents deploying* tag.
- **DetailsTab**: a template mode without brief, title, tags, lead or AI Mode.
- **AiChoiceDrawer** (listing editor): stale choices stay usable, heading *Out of date: brief edited since. Still usable*.

The template head has no actions: Clone, Delete and Start batch live on the [Listing templates](goto:batch-create-lofi/templates) page.
