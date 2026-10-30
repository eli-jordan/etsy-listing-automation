// Same app shell as the first Admin round; this scene adds the Shop tab's own styles.
import type { ReactNode } from "react";
import AdminLayout from "../admin-settings/_layout";
import "./_shop.css";

export default function ShopLayout({ children }: { children: ReactNode }) {
  return <AdminLayout>{children}</AdminLayout>;
}
