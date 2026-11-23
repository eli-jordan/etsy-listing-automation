import type { ReactNode } from "react";

// The prototype draws its own app shell (BackupShell in _parts.tsx), because
// a failing backup changes the shell too: a dot on Admin and a banner on
// every other page.
export default function BackupLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
