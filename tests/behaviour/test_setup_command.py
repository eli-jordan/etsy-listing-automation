"""`setup`, driven end to end with scripted answers and a fake Printify.

No terminal and no network: prompts are answered by matching on the question's
text, so a reordered wizard does not break every test, and the client is the
in-memory fake. What is asserted is the workspace left on disk -- the files
`new` and `plan` will actually read -- rather than the internal sequencing.

The `scripted` fixture and the double behind it are shared with `new`'s tests;
see ``tests/support/scripted.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import typer
import yaml

from etsy_listings import prompts
from etsy_listings.clients.etsy.fakes import FakeEtsyShopClient
from etsy_listings.clients.etsy.models import ReturnPolicy, ShopSection
from etsy_listings.clients.etsy.models import Shop as EtsyShop
from etsy_listings.clients.printify.fakes import FakePrintifyClient
from etsy_listings.clients.printify.models import Shop
from etsy_listings.config.secrets import PRINTIFY_TOKEN_VAR
from etsy_listings.setupcmd.interactive import EtsyAccess, run_setup
from etsy_listings.workspace import layout
from etsy_listings.workspace.workspace import Workspace

ONE_SHOP = [Shop(id=28819281, title="My new store", sales_channel="disconnected")]
CONNECTED_SHOP = [Shop(id=28819281, title="TakeAHikeTees", sales_channel="etsy")]

ETSY_SHOP = EtsyShop(shop_id=12345678, shop_name="TakeAHikeTees", currency_code="NOK")


def _etsy(client: FakeEtsyShopClient | None = None, *, user_id: int | None = 99):  # noqa: ANN202 - a test double
    """An `EtsyAccess` factory, or one that reports no credentials at all.

    `None` is the state a workspace is in before `auth` has run, which is also
    the state every test that is not about discovery wants: `setup` then skips
    the Etsy lookups entirely.
    """
    if client is None:
        return lambda _root: None
    return lambda _root: EtsyAccess(client, user_id)


TWO_SHOPS = [
    Shop(id=1, title="First store", sales_channel="disconnected"),
    Shop(id=2, title="Second store", sales_channel="etsy"),
]


@pytest.fixture(autouse=True)
def _no_ambient_token(monkeypatch) -> None:
    """A developer machine has PRINTIFY_API_TOKEN set. These tests decide for
    themselves whether a token is already available."""
    monkeypatch.delenv(PRINTIFY_TOKEN_VAR, raising=False)


def _factory(client: FakePrintifyClient) -> callable:
    seen: list[str] = []

    def make(token: str):  # noqa: ANN202 - a test double
        seen.append(token)
        return client

    make.tokens = seen  # type: ignore[attr-defined]
    return make


HAPPY_PATH = {
    "token": "printify-token-abc",
    "currency": "NOK",
    "print provider": "Monster Digital",
    "Etsy shop": "",
    "print-on-demand defaults": True,
}


def test_a_fresh_directory_becomes_a_workspace(tmp_path: Path, scripted) -> None:
    """The assertion that matters: what `setup` writes, `Workspace.discover`
    reads."""
    scripted(HAPPY_PATH)

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(),
    )

    workspace = Workspace.discover(root_override=tmp_path)
    assert workspace.defaults.printify.require_shop_id() == 28819281
    assert workspace.defaults.printify.shop_name == "My new store"
    assert workspace.defaults.printify.preferred_print_provider == "Monster Digital"
    assert workspace.defaults.etsy.currency == "NOK"


def test_it_creates_the_directory_skeleton(tmp_path: Path, scripted) -> None:
    scripted(HAPPY_PATH)

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(),
    )

    for name in (layout.DESIGNS_DIR, layout.LISTINGS_DIR, layout.MOCKUP_TEMPLATES_DIR):
        assert (tmp_path / name).is_dir()


def test_the_token_lands_in_the_workspace_env_file(tmp_path: Path, scripted) -> None:
    scripted(HAPPY_PATH)

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(),
    )

    env = (tmp_path / layout.ENV_FILE).read_text(encoding="utf-8")
    assert f"{PRINTIFY_TOKEN_VAR}=printify-token-abc" in env


def test_the_secrets_are_gitignored(tmp_path: Path, scripted) -> None:
    """A workspace is not a git repository by default, but people put one
    around it -- and the two files that would leak a credential are the reason
    this is written at all."""
    scripted(HAPPY_PATH)

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(),
    )

    ignored = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert layout.ENV_FILE in ignored
    assert layout.AUTH_DIR in ignored


def test_the_token_is_verified_before_it_is_stored(tmp_path: Path, scripted) -> None:
    """A token that cannot read `shops.json` is a question to re-ask, not a
    file to write. Writing it and failing later is how a wizard produces a
    workspace that looks configured and is not."""
    script = scripted({**HAPPY_PATH, "token": "bad-token"})

    with pytest.raises(typer.Exit):
        run_setup(
            tmp_path,
            client_factory=_factory(FakePrintifyClient(auth_fails=True)),
            etsy_access=_etsy(),
        )

    assert not (tmp_path / layout.ENV_FILE).exists()
    assert not (tmp_path / layout.SHOP_FILE).exists()
    assert script.asked  # it did ask, rather than failing before the prompt


def test_a_token_already_in_the_environment_is_not_asked_for(
    tmp_path: Path, scripted, monkeypatch
) -> None:
    monkeypatch.setenv(PRINTIFY_TOKEN_VAR, "ambient-token")
    script = scripted({k: v for k, v in HAPPY_PATH.items() if k != "token"})

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(),
    )

    assert not any("token" in question.lower() for question in script.asked)


def test_a_token_already_in_the_env_file_is_reused(tmp_path: Path, scripted) -> None:
    (tmp_path / layout.ENV_FILE).write_text(f"{PRINTIFY_TOKEN_VAR}=from-file\n", encoding="utf-8")
    script = scripted({k: v for k, v in HAPPY_PATH.items() if k != "token"})
    factory = _factory(FakePrintifyClient(ONE_SHOP))

    run_setup(tmp_path, client_factory=factory, etsy_access=_etsy())

    assert not any("token" in question.lower() for question in script.asked)
    assert factory.tokens == ["from-file"]


def test_one_shop_is_selected_without_asking(tmp_path: Path, scripted) -> None:
    script = scripted(HAPPY_PATH)

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(),
    )

    assert not any("shop" in q.lower() and "Printify" in q for q in script.asked)


def test_several_shops_are_a_question(tmp_path: Path, scripted) -> None:
    """Writing products into the wrong shop is not worth risking to save a
    prompt."""
    scripted({**HAPPY_PATH, "Printify shop": "Second store"})

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(TWO_SHOPS)),
        etsy_access=_etsy(),
    )

    assert Workspace.discover(root_override=tmp_path).defaults.printify.require_shop_id() == 2


def test_an_account_with_no_shops_says_what_to_do(tmp_path: Path, scripted, capsys) -> None:
    scripted(HAPPY_PATH)

    with pytest.raises(typer.Exit):
        run_setup(
            tmp_path,
            client_factory=_factory(FakePrintifyClient([])),
            etsy_access=_etsy(),
        )

    assert "printify.com" in capsys.readouterr().err
    assert not (tmp_path / layout.SHOP_FILE).exists()


def test_cancelling_a_question_writes_no_shop_file(tmp_path: Path, scripted) -> None:
    scripted({**HAPPY_PATH, "currency": None})

    with pytest.raises(prompts.Cancelled):
        run_setup(
            tmp_path,
            client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
            etsy_access=_etsy(),
        )

    assert not (tmp_path / layout.SHOP_FILE).exists()


def test_a_blank_etsy_shop_id_is_omitted_rather_than_invented(tmp_path: Path, scripted) -> None:
    scripted(HAPPY_PATH)

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(),
    )

    assert Workspace.discover(root_override=tmp_path).defaults.etsy.shop_id is None


def test_a_connected_printify_shop_finds_the_etsy_shop_by_name(tmp_path: Path, scripted) -> None:
    """Printify names a connected shop after the Etsy shop it publishes to,
    so the selection the user just made *is* the answer (PRD 51)."""
    scripted(HAPPY_PATH)
    etsy = FakeEtsyShopClient([ETSY_SHOP])

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(CONNECTED_SHOP)),
        etsy_access=_etsy(etsy),
    )

    defaults = Workspace.discover(root_override=tmp_path).defaults
    assert defaults.etsy.require_shop_id() == 12345678
    assert defaults.etsy.shop_name == "TakeAHikeTees"
    assert etsy.searched == ["TakeAHikeTees"]


def test_a_shop_that_is_not_connected_falls_back_to_the_signed_in_account(
    tmp_path: Path, scripted
) -> None:
    """An API store has no Etsy name to match on. An Etsy account owns exactly
    one shop, and the stored consent says which account."""
    scripted(HAPPY_PATH)
    etsy = FakeEtsyShopClient(owned=ETSY_SHOP)

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(etsy),
    )

    assert etsy.owner_lookups == [99]
    assert Workspace.discover(root_override=tmp_path).defaults.etsy.require_shop_id() == 12345678


def test_a_near_miss_on_the_name_is_not_taken_as_the_shop(tmp_path: Path, scripted) -> None:
    """Etsy's search is built for buyers browsing. Taking the first row would
    point the workspace at a stranger's shop, so an inexact match asks."""
    scripted({**HAPPY_PATH, "Etsy shop name": ""})
    etsy = FakeEtsyShopClient([EtsyShop(shop_id=7, shop_name="TakeAHikeVintage")])

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(CONNECTED_SHOP)),
        etsy_access=_etsy(etsy, user_id=None),
    )

    assert Workspace.discover(root_override=tmp_path).defaults.etsy.shop_id is None


def test_a_typed_shop_name_is_resolved_to_its_id(tmp_path: Path, scripted) -> None:
    """The last resort, and still not a number: the user names the shop, the
    search turns it into an id (PRD 51)."""
    scripted({**HAPPY_PATH, "Etsy shop name": "TakeAHikeTees"})
    etsy = FakeEtsyShopClient([ETSY_SHOP])

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(etsy, user_id=None),
    )

    assert Workspace.discover(root_override=tmp_path).defaults.etsy.require_shop_id() == 12345678


def test_a_name_etsy_has_never_heard_of_leaves_the_ids_unset(
    tmp_path: Path, scripted, capsys
) -> None:
    scripted({**HAPPY_PATH, "Etsy shop name": "NoSuchShop"})

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(FakeEtsyShopClient([]), user_id=None),
    )

    assert "no shop called" in capsys.readouterr().out
    assert Workspace.discover(root_override=tmp_path).defaults.etsy.shop_id is None


def test_the_currency_comes_from_the_etsy_shop(tmp_path: Path, scripted) -> None:
    """A workspace configured in a currency the shop does not sell in is a
    disagreement nothing surfaces until a price lands wrong (PRD 51)."""
    script = scripted({**HAPPY_PATH, "currency": "USD"})
    etsy = FakeEtsyShopClient(owned=EtsyShop(shop_id=1, shop_name="A shop", currency_code="USD"))

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(etsy),
    )

    prompt = next(q for q in script.defaults_offered if "currency" in q.lower())
    assert script.defaults_offered[prompt] == "USD"


def test_the_shop_section_and_return_policy_are_picked_from_the_live_lists(
    tmp_path: Path, scripted
) -> None:
    scripted(
        {
            **HAPPY_PATH,
            "shop section": "Tees",
            "return policy": "returns",
        }
    )
    etsy = FakeEtsyShopClient(
        owned=ETSY_SHOP,
        sections=[ShopSection(shop_section_id=44, title="Tees")],
        policies=[
            ReturnPolicy(
                return_policy_id=55,
                accepts_returns=True,
                accepts_exchanges=False,
                return_deadline=30,
            )
        ],
    )

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(etsy),
    )

    etsy_defaults = Workspace.discover(root_override=tmp_path).defaults.etsy
    assert etsy_defaults.require_shop_section_id() == 44
    assert etsy_defaults.require_return_policy_id() == 55


def test_without_credentials_it_says_to_run_auth_first(tmp_path: Path, scripted, capsys) -> None:
    """The Etsy half is skipped rather than failed: a workspace is usable for
    rendering and Printify long before Etsy is reachable."""
    scripted(HAPPY_PATH)

    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)), etsy_access=_etsy())

    out = capsys.readouterr().out
    assert "auth" in out
    assert Workspace.discover(root_override=tmp_path).defaults.etsy.shop_id is None


def test_declining_the_defaults_asks_for_each_etsy_field(tmp_path: Path, scripted) -> None:
    scripted(
        {
            **HAPPY_PATH,
            "print-on-demand defaults": False,
            "Who made": "someone_else",
            "When was": "made_to_order",
            "supply": False,
            "renew": "auto",
        }
    )

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(),
    )

    etsy = Workspace.discover(root_override=tmp_path).defaults.etsy
    assert etsy.who_made == "someone_else"
    assert etsy.renewal == "auto"


def test_re_running_keeps_what_a_later_phase_filled_in(tmp_path: Path, scripted) -> None:
    """`setup` fills gaps; it does not correct answers. The Phase 3 ids it
    never asks about must survive a second run."""
    scripted(HAPPY_PATH)
    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(),
    )

    shop_file = tmp_path / layout.SHOP_FILE
    document = yaml.safe_load(shop_file.read_text(encoding="utf-8"))
    document["etsy"]["shop_section_id"] = 44
    document["etsy"]["return_policy_id"] = 55
    shop_file.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    scripted({**HAPPY_PATH, "currency": "USD"})
    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(),
    )

    defaults = Workspace.discover(root_override=tmp_path).defaults
    assert defaults.etsy.require_shop_section_id() == 44
    assert defaults.etsy.require_return_policy_id() == 55
    assert defaults.etsy.currency == "USD", "the answer just given wins over the file"


def test_a_re_run_offers_the_current_values_as_the_defaults(tmp_path: Path, scripted) -> None:
    """Which is what makes "the answer wins" safe: pressing enter through a
    re-run keeps every value, because each prompt arrives pre-filled with what
    the file already says."""
    scripted(HAPPY_PATH)
    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(),
    )

    script = scripted(HAPPY_PATH)
    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(),
    )

    seen = script.defaults_offered
    currency_prompt = next(q for q in seen if "currency" in q.lower())
    provider_prompt = next(q for q in seen if "print provider" in q.lower())
    assert seen[currency_prompt] == "NOK"
    assert seen[provider_prompt] == "Monster Digital"


def test_it_names_both_shops_and_the_next_command(tmp_path: Path, scripted, capsys) -> None:
    """A wizard that stops without saying what it configured reads as one that
    did not finish."""
    scripted(HAPPY_PATH)
    etsy = FakeEtsyShopClient(owned=ETSY_SHOP)

    run_setup(
        tmp_path,
        client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
        etsy_access=_etsy(etsy),
    )

    out = capsys.readouterr().out
    assert "TakeAHikeTees" in out
    assert "My new store" in out
    assert "new" in out.lower()  # points at the next command


# ----------------------------------------------------------------- cancelling

# Every question is a place the user can walk away, and walking away must
# leave no shop.yaml -- that file is what makes a directory a workspace, so
# writing one for an abandoned run is how the next command inherits a
# half-answered configuration.


@pytest.mark.parametrize(
    "cancelled",
    [
        "token",
        "currency",
        "print provider",
        "print-on-demand defaults",
    ],
)
def test_cancelling_any_question_leaves_no_workspace(
    tmp_path: Path, scripted, cancelled: str
) -> None:
    scripted({**HAPPY_PATH, cancelled: None})

    with pytest.raises(prompts.Cancelled):
        run_setup(
            tmp_path,
            client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
            etsy_access=_etsy(),
        )

    assert not (tmp_path / layout.SHOP_FILE).exists()


def test_cancelling_the_shop_choice_leaves_no_workspace(tmp_path: Path, scripted) -> None:
    scripted({**HAPPY_PATH, "Printify shop": None})

    with pytest.raises(prompts.Cancelled):
        run_setup(
            tmp_path,
            client_factory=_factory(FakePrintifyClient(TWO_SHOPS)),
            etsy_access=_etsy(),
        )

    assert not (tmp_path / layout.SHOP_FILE).exists()


@pytest.mark.parametrize("cancelled", ["Who made", "When was", "supply", "renew"])
def test_cancelling_an_individual_etsy_question_leaves_no_workspace(
    tmp_path: Path, scripted, cancelled: str
) -> None:
    scripted(
        {
            **HAPPY_PATH,
            "print-on-demand defaults": False,
            "Who made": "i_did",
            "When was": "made_to_order",
            "supply": False,
            "renew": "manual",
            cancelled: None,
        }
    )

    with pytest.raises(prompts.Cancelled):
        run_setup(
            tmp_path,
            client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
            etsy_access=_etsy(),
        )

    assert not (tmp_path / layout.SHOP_FILE).exists()


def test_a_cancelled_run_leaves_no_token_behind(tmp_path: Path, scripted) -> None:
    """The credential is written only once every question is answered. A
    half-finished run that stored a token would leave a secret on disk in a
    directory the user may well delete rather than re-run."""
    scripted({**HAPPY_PATH, "print-on-demand defaults": None})

    with pytest.raises(prompts.Cancelled):
        run_setup(
            tmp_path,
            client_factory=_factory(FakePrintifyClient(ONE_SHOP)),
            etsy_access=_etsy(),
        )

    assert not (tmp_path / layout.ENV_FILE).exists()
