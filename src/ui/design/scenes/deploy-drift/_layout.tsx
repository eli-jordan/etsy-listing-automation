// The same real app shell the deploy-open-etsy frames sit in.
import type { ReactNode } from "react";
import DeployShell from "../deploy-open-etsy/_layout";
import "./_drift.css";

export default function DeployDriftLayout({ children }: { children: ReactNode }) {
  return <DeployShell>{children}</DeployShell>;
}
