import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { App } from "./App";
import "./index.css";
import { AppShell } from "./shell/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { ListingEditorPage } from "./pages/ListingEditorPage";
import { ListingsPage } from "./pages/ListingsPage";

const container = document.getElementById("root");
if (!container) {
  throw new Error("missing #root element");
}

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/listings" element={<ListingsPage />} />
          {/* Both routes, one component: /listings/new is the editor opened on
              an empty draft, and naming it is what creates it. React Router
              ranks the static segment above the dynamic one. */}
          <Route path="/listings/new" element={<ListingEditorPage />} />
          <Route path="/listings/:name" element={<ListingEditorPage />} />
          {/* The calibrator, unmounted -- mounted here unchanged. */}
          <Route path="/templates" element={<App />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
