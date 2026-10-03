import { NewBatchPage } from "./_NewBatch";

export const meta = {
  title: "New batch — upload refused · v1",
  viewport: "laptop",
  description:
    "Wireframe error state: a ZIP over the 25-design limit is refused before staging, with the recovery spelled out.",
};

export default function NewBatchRefused() {
  return <NewBatchPage refused />;
}
