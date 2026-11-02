import "../../screens/multiArtwork/fakeApi";
import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "../../../src/shell/AppShell";

/** The app's real shell, parked on a listing URL so the nav marks Listings. */
export default function TemplatePositionsLayout({ children }: { children: ReactNode }) {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/listings/night-hike-club" element={children} />
      </Route>
      <Route path="*" element={<Navigate to="/listings/night-hike-club" replace />} />
    </Routes>
  );
}
