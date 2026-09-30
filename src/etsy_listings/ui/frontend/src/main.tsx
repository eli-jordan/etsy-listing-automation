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

// A41: proposals live on the server now; the old browser-local copies go.
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
      {/* Both routes, one component: /listings/new is the editor opened on
          an empty draft, and naming it is what creates it. React Router
          ranks the static segment above the dynamic one. */}
      <Route path="/listings/new" element={<ListingEditorPage />} />
      <Route path="/listings/:name" element={<ListingEditorPage />} />
      {/* Its own route, not a mode of `ListingEditorPage` kept mounted
          behind it (docs/deploy-changes.md decision 9) -- Back returns to
          `/listings/:name`, which re-fetches `ListingDetail` fresh rather
          than reusing state a deploy run may have changed server-side. */}
      <Route path="/listings/:name/deploy" element={<DeployPage />} />
      {/* A35: listing templates. The same two-routes-one-component shape
          as a listing: /new is the unsaved *name it* state (UI doc §1). */}
      <Route path="/listing-templates" element={<ListingTemplatesPage />} />
      <Route path="/listing-templates/new" element={<ListingTemplateEditorPage />} />
      <Route path="/listing-templates/:name" element={<ListingTemplateEditorPage />} />
      {/* Batch creation (batch plan PR 2): choose and drop, review the
          staged designs, then the batch the confirm made. */}
      <Route path="/batches/new" element={<NewBatchPage />} />
      <Route path="/batches/staging/:id" element={<StagingPage />} />
      <Route path="/batches/:id" element={<BatchSummaryPage />} />
      {/* The calibrator, unmounted -- mounted here unchanged. */}
      <Route path="/templates" element={<App />} />
    </Route>,
  ),
);

createRoot(container).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
