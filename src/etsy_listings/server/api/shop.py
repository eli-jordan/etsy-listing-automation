"""The Admin page's Shop tab over HTTP: ``/api/admin/shop``.

Thin by design (ADR-0052): ``core/application/shop_settings.py`` owns the
revision check, validation and lookups; this module builds the clients from
``connections`` and turns refusals into status codes. A refused save is a
:class:`ShopSaveRefusal` body rather than ``{"detail": ...}`` so the page can
tell a conflict from field errors without parsing text.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from etsy_listings.core import connections
from etsy_listings.core.application import shop_settings
from etsy_listings.core.application.refusals import InvalidShopEdit, ShopRevisionConflict
from etsy_listings.core.config.currencies import ETSY_PAYMENTS_CURRENCIES
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.schemas import (
    ConnectionRowBody,
    CurrencyOption,
    EtsyLookupsBody,
    PrintifyLookupsBody,
    ReturnPolicyChoiceBody,
    ReturnPolicyTermsBody,
    ShopConnectionsResponse,
    ShopListingDefaults,
    ShopLookupsResponse,
    ShopPatchRequest,
    ShopSaveRefusal,
    ShopSettingsResponse,
)

router = APIRouter(prefix="/api/admin/shop", tags=["admin"])

_CHANGE_KEYS = {
    "currency": "etsy.currency",
    "preferred_print_provider": "printify.preferred_print_provider",
}
"""Request field to shop.yaml key; every other field is a listing default."""


def _workspace(request: Request) -> Workspace:
    workspace: Workspace = request.app.state.workspace
    return workspace


def _response(view: shop_settings.ShopView) -> ShopSettingsResponse:
    etsy = view.defaults.etsy
    defaults = etsy.listing_defaults
    policy = defaults.return_policy
    return ShopSettingsResponse(
        revision=view.revision,
        currency=etsy.currency,
        supported_currencies=[
            CurrencyOption(code=code, name=name) for code, name in ETSY_PAYMENTS_CURRENCIES.items()
        ],
        listing_defaults=ShopListingDefaults(
            who_made=defaults.who_made,
            when_made=defaults.when_made,
            is_supply=defaults.is_supply,
            production_partner=defaults.production_partner,
            shipping_profile=defaults.shipping_profile,
            return_policy=ReturnPolicyTermsBody(**policy.model_dump()) if policy else None,
            renewal=defaults.renewal,
        ),
        preferred_print_provider=view.defaults.printify.preferred_print_provider,
    )


@router.get("", response_model=ShopSettingsResponse)
def read_shop(request: Request) -> ShopSettingsResponse:
    try:
        return _response(shop_settings.read_shop(_workspace(request)))
    except ConfigLoadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "",
    response_model=ShopSettingsResponse,
    responses={409: {"model": ShopSaveRefusal}, 422: {"model": ShopSaveRefusal}},
)
def edit_shop(request: Request, body: ShopPatchRequest) -> ShopSettingsResponse | JSONResponse:
    sent = body.changes.model_dump(exclude_unset=True)
    changes = {
        _CHANGE_KEYS.get(field, f"etsy.listing_defaults.{field}"): value
        for field, value in sent.items()
    }
    try:
        view = shop_settings.edit_shop(
            _workspace(request), expected_revision=body.revision, changes=changes
        )
    except ShopRevisionConflict as exc:
        return _refusal(409, ShopSaveRefusal(kind="conflict", message=str(exc)))
    except InvalidShopEdit as exc:
        refusal = ShopSaveRefusal(kind="invalid", message=str(exc), field_errors=exc.field_errors)
        return _refusal(422, refusal)
    return _response(view)


def _refusal(status: int, refusal: ShopSaveRefusal) -> JSONResponse:
    return JSONResponse(status_code=status, content=refusal.model_dump())


@router.get("/connections", response_model=ShopConnectionsResponse)
def read_connections(request: Request) -> ShopConnectionsResponse:
    workspace = _workspace(request)
    rows = shop_settings.shop_connections(
        workspace,
        etsy=connections.etsy_shop_client(workspace.root),
        printify=connections.printify_client(workspace),
    )
    return ShopConnectionsResponse(
        etsy=ConnectionRowBody(**asdict(rows.etsy)),
        printify=ConnectionRowBody(**asdict(rows.printify)),
    )


@router.get("/lookups", response_model=ShopLookupsResponse)
def read_lookups(request: Request) -> ShopLookupsResponse:
    """Fresh on every call: the page asks again when its window regains
    focus or the seller retries (ADR-0033 forbids a disk cache for Etsy's)."""
    workspace = _workspace(request)
    lookups = shop_settings.shop_lookups(
        workspace,
        etsy=connections.etsy_listing_client(workspace.root),
        catalog=connections.catalog_client(workspace),
    )
    etsy = lookups.etsy
    return ShopLookupsResponse(
        etsy=EtsyLookupsBody(
            available=etsy.available,
            problem=etsy.problem,
            production_partners=list(etsy.production_partners),
            shipping_profiles=list(etsy.shipping_profiles),
            return_policies=[
                ReturnPolicyChoiceBody(terms=ReturnPolicyTermsBody(**p.terms), label=p.label)
                for p in etsy.return_policies
            ],
        ),
        printify=PrintifyLookupsBody(
            available=lookups.printify.available,
            problem=lookups.printify.problem,
            print_providers=list(lookups.printify.print_providers),
        ),
    )
