// v2 tracks the live template-labels fixtures and the app components; exact state: git
import { SuggestedScreen } from "./_SuggestedLocator";

export const meta = {
  title: "Suggested templates · v2",
  viewport: "laptop",
  description:
    "The Images tab as it opens: search on top, the christmas label from the listing title on, other templates folded. Superseded: labels moved into the search box.",
};

export default function Frame() {
  return (
    <SuggestedScreen
      focus="cc1717-woman-with-peace-sign-and-mug"
      initialOpen="cc1717-woman-with-peace-sign-and-mug"
    />
  );
}
