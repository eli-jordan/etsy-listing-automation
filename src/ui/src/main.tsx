import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import {
  createBrowserRouter,
  createRoutesFromElements,
  Route,
  RouterProvider,
} from "react-router-dom";
import { CalibratorPage } from "./App";
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
import "./phone/index.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("missing #root element");
}

// A data router: React Router's blocker, which useUnsavedWarning needs, exists only there.
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
      <Route path="/templates" element={<CalibratorPage />} />
    </Route>,
  ),
);

createRoot(container).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
