import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import {
  createBrowserRouter,
  createRoutesFromElements,
  Route,
  RouterProvider,
} from "react-router-dom";
import { App } from "./App";
import "./index.css";
import { AppShell } from "./shell/AppShell";
import { AdminPage } from "./pages/admin/AdminPage";
import { BatchDeployPage } from "./pages/BatchDeployPage";
import { BatchSummaryPage } from "./pages/BatchSummaryPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DeployPage } from "./pages/DeployPage";
import { ListingEditorPage } from "./pages/ListingEditorPage";
import { ListingTemplateEditorPage } from "./pages/ListingTemplateEditorPage";
import { ListingTemplatesPage } from "./pages/ListingTemplatesPage";
import { ListingsPage } from "./pages/ListingsPage";
import { NewBatchPage } from "./pages/NewBatchPage";
import { StagingPage } from "./pages/StagingPage";
import { purgeLegacyProposals } from "./pages/editor/aiSeo/legacyProposals";
// Last, so the phone layout's rules come after every desktop rule they adjust.
import "./phone/index.css";

// ADR-0049: proposals live on the server now; the old browser-local copies go.
purgeLegacyProposals(localStorage);

const container = document.getElementById("root");
if (!container) {
  throw new Error("missing #root element");
}

// A data router rather than `<BrowserRouter>`: the listing-template editor
// warns before navigating away from values the server has not written (UI
// doc §3), and React Router's blocker exists only on a data router.
const router = createBrowserRouter(
  createRoutesFromElements(
    <Route element={<AppShell />}>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/listings" element={<ListingsPage />} />
      <Route path="/listings/deploy/:runId" element={<BatchDeployPage />} />
      <Route path="/listings/new" element={<ListingEditorPage />} />
      <Route path="/listings/:name" element={<ListingEditorPage />} />
      <Route path="/listings/:name/deploy" element={<DeployPage />} />
      <Route path="/listing-templates" element={<ListingTemplatesPage />} />
      <Route path="/listing-templates/new" element={<ListingTemplateEditorPage />} />
      <Route path="/listing-templates/:name" element={<ListingTemplateEditorPage />} />
      <Route path="/batches/new" element={<NewBatchPage />} />
      <Route path="/batches/staging/:id" element={<StagingPage />} />
      <Route path="/batches/:id" element={<BatchSummaryPage />} />
      <Route path="/admin" element={<AdminPage />} />
      <Route path="/templates" element={<App />} />
    </Route>,
  ),
);

createRoot(container).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
