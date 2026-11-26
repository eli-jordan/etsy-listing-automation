"""The ``auth`` wizard: every credential this tool needs, each verified against
its own API and stored as soon as it is proved.

The browser opens only once the Etsy app key pair is known good, because a
keystring typo otherwise surfaces as an Etsy error page mid-consent."""

from __future__ import annotations

import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import typer

from etsy_listings.cli import credentials, prompts
from etsy_listings.core import connections
from etsy_listings.core.application import credentials as core_credentials
from etsy_listings.core.application.credentials import TokenSummary
from etsy_listings.core.clients.etsy import callback as callback_module
from etsy_listings.core.clients.etsy import oauth
from etsy_listings.core.clients.etsy.tokens import TokenStore, utcnow
from etsy_listings.core.clients.etsy.transport import OAuthClient, Transport
from etsy_listings.core.clients.printify import PrintifyAuthError
from etsy_listings.core.clients.printify.models import Shop
from etsy_listings.core.clients.printify.protocol import PrintifyClient
from etsy_listings.core.config.secrets import (
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
    EtsyAppKey,
)


@dataclass(frozen=True)
class Backends:
    printify_client: Callable[[str], PrintifyClient] = connections.printify_client_for
    etsy_transport: Callable[[EtsyAppKey], Transport] = Transport
    oauth_client: Callable[[str], OAuthClient] = OAuthClient
    wait_for_redirect: Callable[[], callback_module.Callback] = callback_module.wait_for_redirect
    open_browser: Callable[[str], bool] = webbrowser.open
    now: Callable[[], datetime] = utcnow


Part = Literal["printify", "etsy"]

ALL_PARTS: tuple[Part, ...] = ("printify", "etsy")
"""The credentials `auth` knows how to capture, in the order it asks for them.

Printify first because it is the one every phase so far needs. A part can be
run on its own (`auth etsy`): one credential expiring is the ordinary case.
"""


def run_auth(
    root: Path,
    *,
    backends: Backends | None = None,
    check: bool = False,
    parts: Sequence[Part] = ALL_PARTS,
) -> None:
    back = backends or Backends()
    root.mkdir(parents=True, exist_ok=True)
    store = _token_store(root, back)

    if check:
        _report(root, store, back)
        return

    typer.echo(f"Credentials for the workspace in {root}")
    credentials.announce_gitignore(root)

    if "printify" in parts:
        _printify_token(root, back)
    if "etsy" in parts:
        # One part, not two: the browser flow needs the keystring, and a key pair captured without a
        # sign-in is the half-configured state this command exists to avoid.
        app_key = _etsy_app_key(root, back)
        _etsy_sign_in(app_key, store, back)

    typer.echo("")
    _report(root, store, back)
    if tuple(parts) == ALL_PARTS:
        typer.echo("")
        typer.echo("Next: `etsy-listings setup` writes the workspace and reads back the shop ids.")


def _printify_token(root: Path, back: Backends) -> None:
    def verify(values: tuple[str, ...]) -> tuple[list[Shop], str]:
        try:
            shops = core_credentials.verify_printify_token(
                values[0], client_for=back.printify_client
            )
        except PrintifyAuthError as exc:
            credentials.refuse(str(exc), command="auth")
        return shops, f"verified -- the token can reach {len(shops)} shop(s)."

    captured = credentials.capture(root, credentials.PRINTIFY, verify=verify)
    credentials.store(root, credentials.PRINTIFY, captured)


def _etsy_app_key(root: Path, back: Backends) -> EtsyAppKey:
    def verify(values: tuple[str, ...]) -> tuple[EtsyAppKey, str]:
        app_key = EtsyAppKey(values[0], values[1])
        application_id = core_credentials.verify_etsy_app_key(
            app_key, transport_for=back.etsy_transport
        )
        return app_key, f"verified -- Etsy application {application_id}."

    captured = credentials.capture(
        root,
        credentials.ETSY_APP_KEY,
        verify=verify,
        reuse_message=f"{ETSY_KEYSTRING_VAR} and {ETSY_SHARED_SECRET_VAR} already set.",
    )
    credentials.store(root, credentials.ETSY_APP_KEY, captured)
    return EtsyAppKey(captured.values[0], captured.values[1])


def _etsy_sign_in(app_key: EtsyAppKey, store: TokenStore, back: Backends) -> None:
    summary = core_credentials.summarise(store.load(), now=back.now())
    if summary.present:
        typer.echo("")
        typer.echo(f"  {summary_line(summary)}")
        if not prompts.ask_confirm("Sign in to Etsy again?", default=False):
            return

    sign_in = core_credentials.begin_etsy_sign_in(app_key)

    typer.echo("")
    typer.echo("Opening Etsy's consent page in your browser. If it does not open,")
    typer.echo("paste this URL yourself:")
    typer.echo(f"  {sign_in.url}")
    back.open_browser(sign_in.url)

    typer.echo(f"Waiting for the redirect to {oauth.REDIRECT_URI} ...")
    signed_in = core_credentials.complete_etsy_sign_in(
        sign_in,
        back.wait_for_redirect(),
        oauth_client=back.oauth_client(app_key.keystring),
        tokens=store,
    )
    tokens = signed_in.tokens
    typer.echo(f"  signed in as Etsy user {tokens.user_id}; tokens written to {store.path}")
    if not signed_in.granted_every_scope:
        typer.echo(f"  note: Etsy granted the scopes `{tokens.scope}`")


def summary_line(summary: TokenSummary) -> str:
    if not summary.present:
        return "Etsy sign-in: none stored"
    access = "valid" if summary.access_valid else "expired (refreshed on next use)"
    return (
        f"Etsy sign-in: user {summary.user_id}, access token {access}, "
        f"consent good for {summary.refresh_days} more days"
    )


def renewal_warning(summary: TokenSummary) -> str | None:
    if not summary.renewal_due:
        return None
    return (
        f"Etsy consent expires in {summary.refresh_days} days. "
        f"Run `etsy-listings auth` before then to renew it without interrupting a run."
    )


def _report(root: Path, store: TokenStore, back: Backends) -> None:
    status = core_credentials.credential_status(root, tokens=store, now=back.now())

    typer.echo(summary_line(status.sign_in))
    if status.missing:
        typer.echo(f"Missing: {', '.join(status.missing)}")
    else:
        typer.echo(f"All required credentials present in {status.env_file}")

    warning = renewal_warning(status.sign_in)
    if warning:
        typer.echo(warning)


def _token_store(root: Path, back: Backends) -> TokenStore:
    return connections.etsy_token_store(root, oauth=back.oauth_client, now=back.now)
