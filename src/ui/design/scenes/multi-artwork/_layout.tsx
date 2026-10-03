import "../../screens/multiArtwork/fakeApi";
import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "../../../src/shell/AppShell";

/** The app's real shell around each frame. `design/providers.tsx` already
 * supplies a MemoryRouter at "/"; moving it to a listing URL is what makes
 * the real nav mark Listings as the current page. */
export default function MultiArtworkLayout({ children }: { children: ReactNode }) {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/listings/take-a-hike" element={children} />
      </Route>
      <Route path="*" element={<Navigate to="/listings/take-a-hike" replace />} />
    </Routes>
  );
}
