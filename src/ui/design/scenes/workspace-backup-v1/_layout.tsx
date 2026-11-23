import type { ReactNode } from "react";
import AdminLayout from "../admin-settings/_layout";

export default function BackupLayout({ children }: { children: ReactNode }) {
  return <AdminLayout>{children}</AdminLayout>;
}
