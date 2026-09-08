"""`setup`, driven end to end with scripted answers and a fake Printify.

No terminal and no network: prompts are answered by matching on the question's
text, so a reordered wizard does not break every test, and the client is the
in-memory fake. What is asserted is the workspace left on disk -- the files
`new` and `plan` will actually read -- rather than the internal sequencing.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
import typer
import yaml

from etsy_listings.clients.printify.fakes import FakePrintifyClient
from etsy_listings.clients.printify.models import Shop
from etsy_listings.config.secrets import PRINTIFY_TOKEN_VAR
from etsy_listings.setupcmd import interactive
from etsy_listings.setupcmd.interactive import run_setup
from etsy_listings.workspace import layout
from etsy_listings.workspace.workspace import Workspace

ONE_SHOP = [Shop(id=28819281, title="My new store", sales_channel="disconnected")]
TWO_SHOPS = [
    Shop(id=1, title="First store", sales_channel="disconnected"),
    Shop(id=2, title="Second store", sales_channel="etsy"),
]


class Scripted:
    """Answers keyed by a fragment of the question.

    Keyed rather than ordered on purpose: a wizard's question order is
    presentation, and a test that encodes it fails on every reword.
    """

    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = answers
        self.asked: list[str] = []
        self.defaults_offered: dict[str, str] = {}
        """What each text prompt arrived pre-filled with. A re-run keeps every
        value only if these carry what the file already says."""

    def _answer(self, message: str) -> object:
        self.asked.append(message)
        for fragment, answer in self.answers.items():
            if fragment.lower() in message.lower():
                # A list is successive answers to the same question -- what a
                # user does when a prompt rejects what they typed and asks
                # again. Anything else is the same answer every time.
                if isinstance(answer, list):
                    return answer.pop(0) if len(answer) > 1 else answer[0]
                return answer
        raise AssertionError(f"no scripted answer for {message!r}; asked {self.asked}")

    def text(self, message: str, *, default: str = "") -> str | None:
        """``None`` is what a real prompt returns when the user cancels, so
        that is what it means here too -- not "fall back to the default"."""
        self.defaults_offered[message] = default
        answer = self._answer(message)
        return None if answer is None else str(answer)

    def confirm(self, message: str, *, default: bool = False) -> bool | None:
        answer = self._answer(message)
        return None if answer is None else bool(answer)

    def choose(self, message: str, rows: Sequence[str], *, marker_hint: str = "") -> str | None:
        wanted = self._answer(message)
        if wanted is None:
            return None
        for row in rows:
            if str(wanted) in row:
                return row
        raise AssertionError(f"scripted answer {wanted!r} matches no row in {list(rows)}")


@pytest.fixture
def scripted(monkeypatch) -> callable:
    def install(answers: dict[str, object]) -> Scripted:
        script = Scripted(answers)
        monkeypatch.setattr(interactive.prompts, "text", script.text)
        monkeypatch.setattr(interactive.prompts, "confirm", script.confirm)
        monkeypatch.setattr(interactive.prompts, "choose", script.choose)
        return script

    return install


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

    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    workspace = Workspace.discover(root_override=tmp_path)
    assert workspace.defaults.printify.require_shop_id() == 28819281
    assert workspace.defaults.currency == "NOK"
    assert workspace.defaults.preferred_print_provider == "Monster Digital"


def test_it_creates_the_directory_skeleton(tmp_path: Path, scripted) -> None:
    scripted(HAPPY_PATH)

    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    for name in (layout.DESIGNS_DIR, layout.LISTINGS_DIR, layout.MOCKUP_TEMPLATES_DIR):
        assert (tmp_path / name).is_dir()


def test_the_token_lands_in_the_workspace_env_file(tmp_path: Path, scripted) -> None:
    scripted(HAPPY_PATH)

    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    env = (tmp_path / layout.ENV_FILE).read_text(encoding="utf-8")
    assert f"{PRINTIFY_TOKEN_VAR}=printify-token-abc" in env


def test_the_secrets_are_gitignored(tmp_path: Path, scripted) -> None:
    """A workspace is not a git repository by default, but people put one
    around it -- and the two files that would leak a credential are the reason
    this is written at all."""
    scripted(HAPPY_PATH)

    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    ignored = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert layout.ENV_FILE in ignored
    assert layout.AUTH_DIR in ignored


def test_the_token_is_verified_before_it_is_stored(tmp_path: Path, scripted) -> None:
    """A token that cannot read `shops.json` is a question to re-ask, not a
    file to write. Writing it and failing later is how a wizard produces a
    workspace that looks configured and is not."""
    script = scripted({**HAPPY_PATH, "token": "bad-token"})

    with pytest.raises(typer.Exit):
        run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(auth_fails=True)))

    assert not (tmp_path / layout.ENV_FILE).exists()
    assert not (tmp_path / layout.SHOP_FILE).exists()
    assert script.asked  # it did ask, rather than failing before the prompt


def test_a_token_already_in_the_environment_is_not_asked_for(
    tmp_path: Path, scripted, monkeypatch
) -> None:
    monkeypatch.setenv(PRINTIFY_TOKEN_VAR, "ambient-token")
    script = scripted({k: v for k, v in HAPPY_PATH.items() if k != "token"})

    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    assert not any("token" in question.lower() for question in script.asked)


def test_a_token_already_in_the_env_file_is_reused(tmp_path: Path, scripted) -> None:
    (tmp_path / layout.ENV_FILE).write_text(f"{PRINTIFY_TOKEN_VAR}=from-file\n", encoding="utf-8")
    script = scripted({k: v for k, v in HAPPY_PATH.items() if k != "token"})
    factory = _factory(FakePrintifyClient(ONE_SHOP))

    run_setup(tmp_path, client_factory=factory)

    assert not any("token" in question.lower() for question in script.asked)
    assert factory.tokens == ["from-file"]


def test_one_shop_is_selected_without_asking(tmp_path: Path, scripted) -> None:
    script = scripted(HAPPY_PATH)

    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    assert not any("shop" in q.lower() and "Printify" in q for q in script.asked)


def test_several_shops_are_a_question(tmp_path: Path, scripted) -> None:
    """Writing products into the wrong shop is not worth risking to save a
    prompt."""
    scripted({**HAPPY_PATH, "Printify shop": "Second store"})

    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(TWO_SHOPS)))

    assert Workspace.discover(root_override=tmp_path).defaults.printify.require_shop_id() == 2


def test_an_account_with_no_shops_says_what_to_do(tmp_path: Path, scripted, capsys) -> None:
    scripted(HAPPY_PATH)

    with pytest.raises(typer.Exit):
        run_setup(tmp_path, client_factory=_factory(FakePrintifyClient([])))

    assert "printify.com" in capsys.readouterr().err
    assert not (tmp_path / layout.SHOP_FILE).exists()


def test_cancelling_a_question_writes_no_shop_file(tmp_path: Path, scripted) -> None:
    scripted({**HAPPY_PATH, "currency": None})

    with pytest.raises(typer.Exit):
        run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    assert not (tmp_path / layout.SHOP_FILE).exists()


def test_a_blank_etsy_shop_id_is_omitted_rather_than_invented(tmp_path: Path, scripted) -> None:
    scripted(HAPPY_PATH)

    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    assert Workspace.discover(root_override=tmp_path).defaults.etsy.shop_id is None


def test_an_etsy_shop_id_is_written_when_there_is_one(tmp_path: Path, scripted) -> None:
    scripted({**HAPPY_PATH, "Etsy shop": "12345678"})

    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    assert Workspace.discover(root_override=tmp_path).defaults.etsy.require_shop_id() == 12345678


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

    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    etsy = Workspace.discover(root_override=tmp_path).defaults.etsy
    assert etsy.who_made == "someone_else"
    assert etsy.renewal == "auto"


def test_re_running_keeps_what_a_later_phase_filled_in(tmp_path: Path, scripted) -> None:
    """`setup` fills gaps; it does not correct answers. The Phase 3 ids it
    never asks about must survive a second run."""
    scripted(HAPPY_PATH)
    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    shop_file = tmp_path / layout.SHOP_FILE
    document = yaml.safe_load(shop_file.read_text(encoding="utf-8"))
    document["etsy"]["shop_section_id"] = 44
    document["etsy"]["return_policy_id"] = 55
    shop_file.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    scripted({**HAPPY_PATH, "currency": "USD"})
    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    defaults = Workspace.discover(root_override=tmp_path).defaults
    assert defaults.etsy.require_shop_section_id() == 44
    assert defaults.etsy.require_return_policy_id() == 55
    assert defaults.currency == "USD", "the answer just given wins over the file"


def test_a_re_run_offers_the_current_values_as_the_defaults(tmp_path: Path, scripted) -> None:
    """Which is what makes "the answer wins" safe: pressing enter through a
    re-run keeps every value, because each prompt arrives pre-filled with what
    the file already says."""
    scripted(HAPPY_PATH)
    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    script = scripted(HAPPY_PATH)
    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    seen = script.defaults_offered
    currency_prompt = next(q for q in seen if "currency" in q.lower())
    provider_prompt = next(q for q in seen if "print provider" in q.lower())
    assert seen[currency_prompt] == "NOK"
    assert seen[provider_prompt] == "Monster Digital"


def test_it_says_that_etsy_auth_is_still_to_come(tmp_path: Path, scripted, capsys) -> None:
    """A wizard that stops without saying so reads as a wizard that finished."""
    scripted(HAPPY_PATH)

    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    out = capsys.readouterr().out
    assert "etsy" in out.lower()
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
        "Etsy shop",
        "print-on-demand defaults",
    ],
)
def test_cancelling_any_question_leaves_no_workspace(
    tmp_path: Path, scripted, cancelled: str
) -> None:
    scripted({**HAPPY_PATH, cancelled: None})

    with pytest.raises(typer.Exit):
        run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    assert not (tmp_path / layout.SHOP_FILE).exists()


def test_cancelling_the_shop_choice_leaves_no_workspace(tmp_path: Path, scripted) -> None:
    scripted({**HAPPY_PATH, "Printify shop": None})

    with pytest.raises(typer.Exit):
        run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(TWO_SHOPS)))

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

    with pytest.raises(typer.Exit):
        run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    assert not (tmp_path / layout.SHOP_FILE).exists()


def test_a_non_numeric_etsy_shop_id_is_asked_again(tmp_path: Path, scripted, capsys) -> None:
    """Etsy's shop id is a number, and the shop's *name* is the thing a user
    reaches for first. Rejecting it and re-asking beats writing a string into
    a field typed as an int and failing at load."""
    script = scripted({**HAPPY_PATH, "Etsy shop": ["my-cool-shop", "12345678"]})

    run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    assert sum("Etsy shop id" in q for q in script.asked) == 2
    assert "not a number" in capsys.readouterr().out
    assert Workspace.discover(root_override=tmp_path).defaults.etsy.require_shop_id() == 12345678


def test_a_cancelled_run_leaves_no_token_behind(tmp_path: Path, scripted) -> None:
    """The credential is written only once every question is answered. A
    half-finished run that stored a token would leave a secret on disk in a
    directory the user may well delete rather than re-run."""
    scripted({**HAPPY_PATH, "print-on-demand defaults": None})

    with pytest.raises(typer.Exit):
        run_setup(tmp_path, client_factory=_factory(FakePrintifyClient(ONE_SHOP)))

    assert not (tmp_path / layout.ENV_FILE).exists()
