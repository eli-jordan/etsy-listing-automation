import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createListing, listGarmentProfiles, listListingDesigns } from "../api/listings";
import type { GarmentProfileSummary, ListingDesignSummary } from "../types";

/**
 * "+ New listing" (phase-5-listings-ui.md): a simplified inline flow, not a
 * port of the `new` CLI wizard -- pick a design and an *existing* garment
 * profile; colours default to every colour the garment profile offers, and
 * the pricing plan is resolved server-side. Creating garment
 * profiles/pricing plans from the UI is deferred. A routed page
 * (`/listings/new`), not a dialog, per the plan's router bullet.
 */

export function NewListingPage() {
  const navigate = useNavigate();
  const [designs, setDesigns] = useState<ListingDesignSummary[]>([]);
  const [profiles, setProfiles] = useState<GarmentProfileSummary[]>([]);
  const [name, setName] = useState("");
  const [design, setDesign] = useState("");
  const [garmentProfile, setGarmentProfile] = useState("");
  const [status, setStatus] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    listListingDesigns()
      .then((loaded) => {
        setDesigns(loaded);
        setDesign((current) => current || loaded[0]?.name || "");
      })
      .catch(() => setStatus("failed to load designs"));
    listGarmentProfiles()
      .then((loaded) => {
        setProfiles(loaded);
        setGarmentProfile((current) => current || loaded[0]?.name || "");
      })
      .catch(() => setStatus("failed to load garment profiles"));
  }, []);

  const selectedProfile = profiles.find((p) => p.name === garmentProfile);
  const canSubmit = name.trim() !== "" && design !== "" && garmentProfile !== "" && !submitting;

  function handleSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setStatus("");
    createListing({
      name,
      design,
      garment_profile: garmentProfile,
      colors: selectedProfile ? Object.keys(selectedProfile.colors) : [],
    })
      .then((created) => navigate(`/listings/${encodeURIComponent(created.name)}`))
      .catch(() => {
        setStatus("could not create listing");
        setSubmitting(false);
      });
  }

  return (
    <div>
      <div className="page-head">
        <span className="page-head__crumb" onClick={() => navigate("/listings")}>
          Listings
        </span>
        <span className="page-head__sep">/</span>
        <h1 className="page-head__title">New listing</h1>
      </div>

      <fieldset>
        <legend>New listing</legend>

        <div className="field">
          <label htmlFor="new-listing-name">Name</label>
          <input
            id="new-listing-name"
            className="input"
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>

        <div className="field">
          <label htmlFor="new-listing-design">Design</label>
          <select
            id="new-listing-design"
            value={design}
            onChange={(event) => setDesign(event.target.value)}
          >
            {designs.map((d) => (
              <option key={d.name} value={d.name}>
                {d.name}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="new-listing-garment">Garment profile</label>
          <select
            id="new-listing-garment"
            value={garmentProfile}
            onChange={(event) => setGarmentProfile(event.target.value)}
          >
            {profiles.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        <p className="app__status" role="status">
          {status}
        </p>

        <div className="kind-picker__actions">
          <button type="button" className="btn btn-secondary" onClick={() => navigate("/listings")}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={!canSubmit}
          >
            Create
          </button>
        </div>
      </fieldset>
    </div>
  );
}
