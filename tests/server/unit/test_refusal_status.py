"""The app's one refusal table (``app.py``'s ``REFUSAL_STATUS``): each refusal
category, and a real refusal of each, answers with its status and its own
message as the detail. Routes only let refusals through, so this is where the
mapping itself is proven; the route tests prove the wiring."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from etsy_listings.core.application.refusals import (
    BatchMissingError,
    CalibrationDesignMissingError,
    ProposalReplacedError,
    ReservedListingTemplateNameError,
    TemplateKindRefusedError,
)
from etsy_listings.core.batches import ConfirmRefusedError
from etsy_listings.core.errors import (
    ConflictError,
    MissingError,
    RefusedError,
    StaleError,
    UserFacingError,
)
from etsy_listings.core.workspace.calibration import (
    CalibrationChangedError,
    CalibrationRequestReusedError,
)
from etsy_listings.core.workspace.workspace import InvalidNameError
from etsy_listings.server.api.app import REFUSAL_STATUS, register_refusals

CATEGORIES = [
    (InvalidNameError("a:b"), 400),
    (MissingError("gone"), 404),
    (ConflictError("taken"), 409),
    (StaleError("moved"), 412),
    (RefusedError("not an image"), 422),
]

# One real refusal per category, including the ones whose status the routes
# once decided differently: a missing test design was a 400, and the two
# calibration conflicts were told apart by their message text.
REFUSALS = [
    (ReservedListingTemplateNameError("draft"), 400),
    (CalibrationDesignMissingError("old-upload"), 404),
    (BatchMissingError("b1"), 404),
    (ConfirmRefusedError("name every row first"), 409),
    (CalibrationRequestReusedError("Save request ID was reused with different content"), 409),
    (CalibrationChangedError("Calibration changed; reload before saving"), 412),
    (ProposalReplacedError("example"), 412),
    (TemplateKindRefusedError("no photos in 'empty'"), 422),
]


def _answer(refusal: Exception) -> tuple[int, object]:
    app = FastAPI()
    register_refusals(app)

    @app.get("/refuse")
    def refuse() -> None:
        raise refusal

    response = TestClient(app).get("/refuse")
    return response.status_code, response.json()


def test_every_category_is_in_the_table() -> None:
    assert {type(refusal) for refusal, _ in CATEGORIES} == set(REFUSAL_STATUS)


@pytest.mark.parametrize(
    ("refusal", "status"), CATEGORIES + REFUSALS, ids=lambda value: type(value).__name__
)
def test_a_refusal_answers_with_its_category_status(refusal: Exception, status: int) -> None:
    assert _answer(refusal) == (status, {"detail": str(refusal)})


def test_a_refusal_without_a_category_is_not_answered() -> None:
    """A ``UserFacingError`` the table does not know stays a defect, not a
    guessed status."""
    app = FastAPI()
    register_refusals(app)

    @app.get("/refuse")
    def refuse() -> None:
        raise UserFacingError("uncategorized")

    response = TestClient(app, raise_server_exceptions=False).get("/refuse")
    assert response.status_code == 500
