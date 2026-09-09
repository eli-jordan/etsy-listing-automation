"""Sequencing the questions ``auth`` asks, and doing the I/O it decides on.

Three orderings matter here and none of them is arbitrary:

- **The ``.gitignore`` is written before the first secret.** ``auth`` runs
  before ``setup``, so it may be the first thing ever written into this
  directory -- and a directory inside an existing repository is one where a
  ``.env`` written a moment too early is already tracked (PRD 49).
- **Every credential is verified before it is stored**, against its own API:
  Printify's shop list, Etsy's ping, and for the bearer, the token exchange
  itself. Storing an unverified credential produces a workspace that looks
  configured and is not.
- **The browser is opened after the app key pair is known good.** A keystring
  typo surfaces as an Etsy error page mid-consent otherwise, which is a long
  way from the question that caused it.

Every external effect arrives through :class:`Backends`, so the whole flow --
browser included -- runs in a test without a socket or a network.
"""

from __future__ import annotations

import os
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NoReturn

import typer

from etsy_listings import prompts
from etsy_listings.authcmd import logic
from etsy_listings.clients.etsy import callback as callback_module
from etsy_listings.clients.etsy import oauth
from etsy_listings.clients.etsy.tokens import TokenStore, utcnow
from etsy_listings.clients.etsy.transport import OAuthClient, Transport
from etsy_listings.clients.printify import HttpPrintifyClient, PrintifyAuthError
from etsy_listings.clients.printify import Transport as PrintifyTransport
from etsy_listings.clients.printify.protocol import PrintifyClient
from etsy_listings.config.secrets import (
    ANTHROPIC_KEY_VAR,
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
    PRINTIFY_TOKEN_VAR,
    EtsyAppKey,
    Secrets,
)
from etsy_listings.workspace import layout, scaffold


@dataclass(frozen=True)
class Backends:
    """Everything that leaves the process, in one injectable value.

    A single object rather than six keyword arguments: a test replaces the two
    it cares about and inherits the rest, and a new external effect does not
    change the signature of every caller.
    """

    printify_client: Callable[[str], PrintifyClient] = lambda token: HttpPrintifyClient(
        PrintifyTransport(token)
    )
    etsy_transport: Callable[[EtsyAppKey], Transport] = Transport
    oauth_client: Callable[[str], OAuthClient] = OAuthClient
    wait_for_redirect: Callable[[], callback_module.Callback] = callback_module.wait_for_redirect
    open_browser: Callable[[str], bool] = webbrowser.open
    now: Callable[[], datetime] = utcnow


def run_auth(root: Path, *, backends: Backends | None = None, check: bool = False) -> None:
    """Capture (or report on) every credential this tool needs.

    ``check`` reports and writes nothing -- it is the answer to "am I still
    signed in?", which should never be a question you have to risk changing
    something to ask.
    """
    back = backends or Backends()
    root.mkdir(parents=True, exist_ok=True)
    store = _token_store(root, back)

    if check:
        _report(root, store, back)
        return

    typer.echo(f"Credentials for the workspace in {root}")
    if scaffold.update_gitignore(root):
        typer.echo("  wrote .gitignore (.env, .auth/ and .cache/ stay out of git)")

    _printify_token(root, back)
    app_key = _etsy_app_key(root, back)
    _etsy_sign_in(root, app_key, store, back)
    _anthropic_key(root)

    typer.echo("")
    _report(root, store, back)
    typer.echo("")
    typer.echo("Next: `etsy-listings setup` writes the workspace and reads back the shop ids.")


# --------------------------------------------------------------- credentials


def _printify_token(root: Path, back: Backends) -> None:
    existing = _stored(root, PRINTIFY_TOKEN_VAR)
    if existing:
        typer.echo(f"{PRINTIFY_TOKEN_VAR} already set -- leaving it alone.")
        return

    typer.echo("")
    typer.echo("A Printify personal access token is needed to read the catalog")
    typer.echo("and create products. Generate one at:")
    typer.echo("  https://printify.com/app/account/connections")
    typer.echo("It needs the catalog, shops and products scopes.")
    token = prompts.ask_text("Printify API token:")

    try:
        shops = back.printify_client(token).shops()
    except PrintifyAuthError as exc:
        _refuse(str(exc))
    typer.echo(f"  verified -- the token can reach {len(shops)} shop(s).")
    scaffold.write_env_value(root, PRINTIFY_TOKEN_VAR, token)


def _etsy_app_key(root: Path, back: Backends) -> EtsyAppKey:
    """The keystring and shared secret, verified together by one ping.

    Together because they fail together: `x-api-key` carries both, so a ping
    cannot say which half was wrong, and asking for them one at a time with a
    verification between would promise a precision Etsy does not offer.
    """
    keystring = _stored(root, ETSY_KEYSTRING_VAR)
    shared_secret = _stored(root, ETSY_SHARED_SECRET_VAR)

    if keystring and shared_secret:
        typer.echo(f"{ETSY_KEYSTRING_VAR} and {ETSY_SHARED_SECRET_VAR} already set.")
        return EtsyAppKey(keystring, shared_secret)

    typer.echo("")
    typer.echo("Etsy identifies this application by a key *pair*, both on:")
    typer.echo("  https://www.etsy.com/developers/your-apps")
    typer.echo("The shared secret is hidden behind the visibility icon beside it.")
    keystring = keystring or prompts.ask_text("Etsy keystring:")
    shared_secret = shared_secret or prompts.ask_text("Etsy shared secret:")

    app_key = EtsyAppKey(keystring.strip(), shared_secret.strip())
    application_id = back.etsy_transport(app_key).ping()
    typer.echo(f"  verified -- Etsy application {application_id}.")

    scaffold.write_env_value(root, ETSY_KEYSTRING_VAR, app_key.keystring)
    scaffold.write_env_value(root, ETSY_SHARED_SECRET_VAR, app_key.shared_secret)
    return app_key


def _etsy_sign_in(root: Path, app_key: EtsyAppKey, store: TokenStore, back: Backends) -> None:
    """The browser round trip, or a reason not to make it.

    An existing consent is left alone by default. Re-authorising is harmless
    but not free -- it costs a browser, an Etsy password and a consent screen
    -- and a wizard that spends those on a re-run teaches people not to re-run
    it.
    """
    summary = logic.summarise(store.load(), now=back.now())
    if summary.present:
        typer.echo("")
        typer.echo(f"  {summary.line()}")
        if not prompts.ask_confirm("Sign in to Etsy again?", default=False):
            return

    pkce = oauth.Pkce.generate()
    state = oauth.new_state()
    url = oauth.authorize_url(keystring=app_key.keystring, pkce=pkce, state=state)

    typer.echo("")
    typer.echo("Opening Etsy's consent page in your browser. If it does not open,")
    typer.echo("paste this URL yourself:")
    typer.echo(f"  {url}")
    back.open_browser(url)

    typer.echo(f"Waiting for the redirect to {oauth.REDIRECT_URI} ...")
    redirect = back.wait_for_redirect()
    oauth.check_state(sent=state, received=redirect.state)

    response = back.oauth_client(app_key.keystring).exchange(
        code=redirect.code, verifier=pkce.verifier
    )
    tokens = store.record(response)
    typer.echo(f"  signed in as Etsy user {tokens.user_id}; tokens written to {store.path}")
    if tokens.scope != " ".join(oauth.SCOPES):
        # Etsy grants a subset silently when an app's registration allows
        # less than it asked for, and the shortfall only shows up later as a
        # 403 on one endpoint. Cheaper to read it here.
        typer.echo(f"  note: Etsy granted the scopes `{tokens.scope}`")


def _anthropic_key(root: Path) -> None:
    """Optional, and asked last.

    Nothing before Phase 4 uses it, so a blank answer is a complete run rather
    than a skipped step -- and unverified, because Anthropic has no free
    endpoint that proves a key without spending on one.
    """
    if _stored(root, ANTHROPIC_KEY_VAR):
        typer.echo(f"{ANTHROPIC_KEY_VAR} already set -- leaving it alone.")
        return

    typer.echo("")
    typer.echo("An Anthropic API key generates listing copy (Phase 4; not needed yet).")
    typer.echo("  https://console.anthropic.com/settings/keys")
    key = prompts.ask_text("Anthropic API key (blank to skip):", allow_blank=True)
    if not key.strip():
        typer.echo("  skipped.")
        return
    scaffold.write_env_value(root, ANTHROPIC_KEY_VAR, key.strip())


# -------------------------------------------------------------------- report


def _report(root: Path, store: TokenStore, back: Backends) -> None:
    secrets = Secrets.load(root / layout.ENV_FILE)
    summary = logic.summarise(store.load(), now=back.now())

    typer.echo(summary.line())
    missing = logic.missing_credentials(secrets)
    if missing:
        typer.echo(f"Missing: {', '.join(missing)}")
    else:
        typer.echo(f"All required credentials present in {secrets.env_file}")
    for name in logic.optional_credentials(secrets):
        typer.echo(f"Optional, not set: {name}")

    warning = logic.renewal_warning(summary)
    if warning:
        typer.echo(warning)


def _token_store(root: Path, back: Backends) -> TokenStore:
    """The store, wired to refresh through whatever keystring is on disk.

    The keystring is resolved *inside* the refresh rather than captured now,
    because `auth --check` builds a store for a workspace that may have no
    credentials at all, and demanding one to answer "what have I got?" would
    fail the question it was asked.
    """

    def refresh(refresh_token: str) -> oauth.TokenResponse:
        app_key = Secrets.load(root / layout.ENV_FILE).require_etsy_app_key()
        return back.oauth_client(app_key.keystring).refresh(refresh_token)

    return TokenStore(
        root / layout.AUTH_DIR / layout.ETSY_TOKENS_FILE,
        refresh=refresh,
        now=back.now,
    )


def _stored(root: Path, variable: str) -> str | None:
    """A credential this machine already has, environment first.

    The same precedence :class:`Secrets` uses, so `auth` cannot disagree with
    the rest of the tool about which credential is in play -- a wizard that
    stores a token the next command then ignores is worse than one that never
    ran.
    """
    from_env = os.environ.get(variable)
    if from_env:
        return from_env
    secrets = Secrets.load(root / layout.ENV_FILE)
    return {
        PRINTIFY_TOKEN_VAR: secrets.printify_api_token,
        ETSY_KEYSTRING_VAR: secrets.etsy_keystring,
        ETSY_SHARED_SECRET_VAR: secrets.etsy_shared_secret,
        ANTHROPIC_KEY_VAR: secrets.anthropic_api_key,
    }[variable]


def _refuse(message: str) -> NoReturn:
    typer.echo("", err=True)
    typer.echo(message, err=True)
    typer.echo("Nothing was written -- re-run `auth` with a working credential.", err=True)
    raise typer.Exit(code=1)
