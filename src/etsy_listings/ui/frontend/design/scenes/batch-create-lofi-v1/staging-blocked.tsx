import { StagingPage } from "./_Staging";

export const meta = {
  title: "New batch — names need fixing · v1",
  viewport: "laptop",
  description:
    "Wireframe state: an empty slug and a manually typed name conflict block Create until fixed.",
};

export default function StagingBlocked() {
  return <StagingPage blocked />;
}
