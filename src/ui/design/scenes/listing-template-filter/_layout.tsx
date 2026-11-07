import "../../screens/multiArtwork/fakeApi";
import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "../../../src/shell/AppShell";

/** The app's real shell, parked on a listing URL so the nav marks Listings. */
export default function ListingTemplateFilterLayout({ children }: { children: ReactNode }) {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/listings/santa-cookie-crew" element={children} />
      </Route>
      <Route path="*" element={<Navigate to="/listings/santa-cookie-crew" replace />} />
    </Routes>
  );
}
