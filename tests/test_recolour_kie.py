"""The create-mockup-template-cc1717 skill's `kie.py`: which colours it generates, how it
survives API failures, and how it reports running out of credits."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from email.message import Message
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from PIL import Image

SCRIPT = Path(__file__).parents[1] / ".claude/skills/create-mockup-template-cc1717/kie.py"
KEY = "secret-key"


@pytest.fixture(scope="module")
def kie() -> ModuleType:
    spec = importlib.util.spec_from_file_location("kie", SCRIPT)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["kie"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_waiting(kie: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kie, "RETRY_SECONDS", (0, 0))
    monkeypatch.setattr(kie, "POLL_SECONDS", 0)
    monkeypatch.setenv("KIE_API_KEY", KEY)


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    (tmp_path / "briefs").mkdir()
    (tmp_path / "out").mkdir()
    (tmp_path / "source.png").write_bytes(b"source")
    for slug in ("white", "pepper", "red"):
        (tmp_path / "briefs" / f"{slug}.md").write_text(slug, encoding="utf-8")
    (tmp_path / "out" / "white.png").write_bytes(b"done")
    return tmp_path


@pytest.fixture
def generated(kie: ModuleType, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    done: list[str] = []
    monkeypatch.setattr(kie, "balance", lambda _key: 1000.0)
    monkeypatch.setattr(kie, "upload", lambda _path, _key: "url")
    monkeypatch.setattr(
        kie, "generate", lambda _url, _brief, output, _key: done.append(output.stem)
    )
    return done


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (8, 8), "red").save(buffer, "PNG")
    return buffer.getvalue()


def ok(data: object) -> bytes:
    return json.dumps({"code": 200, "msg": "success", "data": data}).encode()


SUCCESS_RECORD = ok(
    {"state": "success", "resultJson": json.dumps({"resultUrls": ["https://cdn/result.png"]})}
)


class FakeApi:
    """Answers each endpoint from its own script of bodies or exceptions; the last entry
    repeats."""

    def __init__(self, **routes: list[bytes | Exception]) -> None:
        self.routes = routes
        self.seen: list[str] = []

    def __call__(self, request: urllib.request.Request) -> bytes:
        url = request.full_url
        self.seen.append(url)
        for name, answers in self.routes.items():
            if name in url:
                answer = answers.pop(0) if len(answers) > 1 else answers[0]
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise AssertionError(url)

    def count(self, name: str) -> int:
        return sum(name in url for url in self.seen)


@pytest.fixture
def use_api(kie: ModuleType, monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeApi]:
    def install(**routes: list[bytes | Exception]) -> FakeApi:
        api = FakeApi(**routes)
        monkeypatch.setattr(kie, "fetch", api)
        return api

    return install


def edit_paths(tmp_path: Path, text: str = "Do it") -> tuple[Path, Path]:
    brief = tmp_path / "brief.md"
    brief.write_text(text, encoding="utf-8")
    return brief, tmp_path / "out" / "generated.png"


def test_colours_generates_only_those_missing_a_photo(
    kie: ModuleType, run_dir: Path, generated: list[str]
) -> None:
    kie.colours(argparse.Namespace(run_dir=str(run_dir), slugs=[]))
    assert sorted(generated) == ["pepper", "red"]


def test_named_colours_regenerate_even_with_a_photo(
    kie: ModuleType, run_dir: Path, generated: list[str]
) -> None:
    kie.colours(argparse.Namespace(run_dir=str(run_dir), slugs=["white"]))
    assert generated == ["white"]


def test_nothing_pending_says_so_and_uploads_nothing(
    kie: ModuleType, run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for slug in ("pepper", "red"):
        (run_dir / "out" / f"{slug}.png").write_bytes(b"done")
    kie.colours(argparse.Namespace(run_dir=str(run_dir), slugs=[]))
    assert "Nothing to generate" in capsys.readouterr().out


def test_too_few_credits_stops_and_lists_what_was_not_generated(
    kie: ModuleType, run_dir: Path, generated: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(kie, "balance", lambda _key: 11.0)
    with pytest.raises(kie.KieError, match=kie.OUT_OF_CREDITS) as raised:
        kie.colours(argparse.Namespace(run_dir=str(run_dir), slugs=[]))
    assert "pepper, red" in str(raised.value)
    assert generated == []


def test_credits_running_out_mid_run_is_reported(
    kie: ModuleType, run_dir: Path, generated: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    balances: Iterator[float] = iter([100.0, 0.0])
    monkeypatch.setattr(kie, "balance", lambda _key: next(balances))

    def fail(_url: str, _brief: Path, _output: Path, _key: str) -> None:
        raise kie.KieError("rejected")

    monkeypatch.setattr(kie, "generate", fail)
    with pytest.raises(SystemExit, match=kie.OUT_OF_CREDITS):
        kie.colours(argparse.Namespace(run_dir=str(run_dir), slugs=["red"]))


def test_a_402_says_out_of_credits_whatever_the_balance(
    kie: ModuleType, use_api: Callable[..., FakeApi]
) -> None:
    use_api(credit=[json.dumps({"code": 402, "msg": "Insufficient"}).encode()])
    with pytest.raises(kie.KieError, match=kie.OUT_OF_CREDITS):
        kie.call(f"{kie.API}/chat/credit", KEY)


def test_one_failure_leaves_the_other_colours_generating_and_lists_it(
    kie: ModuleType, run_dir: Path, generated: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    done: list[str] = []

    def flaky(_url: str, _brief: Path, output: Path, _key: str) -> None:
        if output.stem == "pepper":
            raise kie.TransientError("no connection")
        done.append(output.stem)

    monkeypatch.setattr(kie, "generate", flaky)
    with pytest.raises(SystemExit, match="pepper: no connection"):
        kie.colours(argparse.Namespace(run_dir=str(run_dir), slugs=[]))
    assert done == ["red"]


def test_a_failed_balance_check_keeps_the_failure_list(
    kie: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(_key: str) -> float:
        raise kie.TransientError("outage")

    monkeypatch.setattr(kie, "balance", down)
    assert kie.failure_message(["red: failed"], KEY) == "red: failed"


@pytest.mark.parametrize(
    "body",
    [b"not json", json.dumps({"code": 200, "data": None}).encode()],
    ids=["unreadable", "empty"],
)
def test_a_bad_response_while_polling_is_ridden_out(
    kie: ModuleType, use_api: Callable[..., FakeApi], body: bytes
) -> None:
    use_api(recordInfo=[body, SUCCESS_RECORD])
    assert kie.finished_url("task", KEY) == "https://cdn/result.png"


def test_a_rate_limit_while_polling_is_ridden_out(
    kie: ModuleType, use_api: Callable[..., FakeApi]
) -> None:
    limited = json.dumps({"code": 429, "msg": "slow down"}).encode()
    use_api(recordInfo=[limited, limited, SUCCESS_RECORD])
    assert kie.finished_url("task", KEY) == "https://cdn/result.png"


@pytest.mark.parametrize("result", ["{}", '{"resultUrls": []}', "broken"])
def test_a_success_with_no_image_is_a_failure_not_a_crash(
    kie: ModuleType, use_api: Callable[..., FakeApi], result: str
) -> None:
    use_api(recordInfo=[ok({"state": "success", "resultJson": result})])
    with pytest.raises(kie.KieError, match="no image"):
        kie.finished_url("task", KEY)


def test_a_rate_limited_task_is_created_once_it_gets_through(
    kie: ModuleType, tmp_path: Path, use_api: Callable[..., FakeApi]
) -> None:
    limited = json.dumps({"code": 429, "msg": "slow down"}).encode()
    api = use_api(
        createTask=[limited, ok({"taskId": "t1"})],
        recordInfo=[SUCCESS_RECORD],
        **{"cdn/result": [png()]},
    )
    brief, output = edit_paths(tmp_path)
    kie.generate("url", brief, output, KEY)
    assert api.count("createTask") == 2
    assert output.is_file()


def test_a_timed_out_create_is_not_repeated(
    kie: ModuleType, tmp_path: Path, use_api: Callable[..., FakeApi]
) -> None:
    api = use_api(createTask=[kie.TransientError("timed out")])
    brief, output = edit_paths(tmp_path)
    with pytest.raises(kie.TransientError):
        kie.generate("url", brief, output, KEY)
    assert api.count("createTask") == 1


def test_a_download_that_keeps_failing_is_collected_by_a_rerun_without_a_new_task(
    kie: ModuleType, tmp_path: Path, use_api: Callable[..., FakeApi]
) -> None:
    down = kie.TransientError("truncated")
    api = use_api(
        createTask=[ok({"taskId": "t1"})],
        recordInfo=[SUCCESS_RECORD],
        **{"cdn/result": [down, down, down, png()]},
    )
    brief, output = edit_paths(tmp_path)
    with pytest.raises(kie.TransientError):
        kie.generate("url", brief, output, KEY)
    assert output.with_suffix(".task").is_file()

    kie.generate("url", brief, output, KEY)

    assert api.count("createTask") == 1
    assert output.is_file()
    assert not output.with_suffix(".task").exists()


def test_a_changed_brief_does_not_collect_the_old_task(
    kie: ModuleType, tmp_path: Path, use_api: Callable[..., FakeApi]
) -> None:
    api = use_api(
        createTask=[ok({"taskId": "new"})],
        recordInfo=[SUCCESS_RECORD],
        **{"cdn/result": [png()]},
    )
    brief, output = edit_paths(tmp_path, "New words")
    output.parent.mkdir()
    output.with_suffix(".task").write_text("olddigest old", encoding="utf-8")
    kie.generate("url", brief, output, KEY)
    assert any("taskId=new" in url for url in api.seen)


def test_a_failed_task_is_forgotten_so_a_rerun_starts_afresh(
    kie: ModuleType, tmp_path: Path, use_api: Callable[..., FakeApi]
) -> None:
    use_api(
        createTask=[ok({"taskId": "t1"})],
        recordInfo=[ok({"state": "fail", "failCode": "500", "failMsg": "refused"})],
    )
    brief, output = edit_paths(tmp_path)
    with pytest.raises(kie.KieError, match="refused"):
        kie.generate("url", brief, output, KEY)
    assert not output.with_suffix(".task").exists()


def test_regenerating_keeps_the_previous_rounds(
    kie: ModuleType, tmp_path: Path, use_api: Callable[..., FakeApi]
) -> None:
    use_api(
        createTask=[ok({"taskId": "t1"})],
        recordInfo=[SUCCESS_RECORD],
        **{"cdn/result": [png()]},
    )
    brief, output = edit_paths(tmp_path)
    for _ in range(3):
        kie.generate("url", brief, output, KEY)
    names = sorted(path.name for path in output.parent.iterdir())
    assert names == ["generated-round1.keep", "generated-round2.keep", "generated.png"]


def test_the_saved_photo_is_rgb(
    kie: ModuleType, tmp_path: Path, use_api: Callable[..., FakeApi]
) -> None:
    use_api(
        createTask=[ok({"taskId": "t1"})],
        recordInfo=[SUCCESS_RECORD],
        **{"cdn/result": [png()]},
    )
    brief, output = edit_paths(tmp_path)
    kie.generate("url", brief, output, KEY)
    with Image.open(output) as image:
        assert image.mode == "RGB"


def test_the_prompt_leaves_out_the_note_headings(kie: ModuleType, tmp_path: Path) -> None:
    brief, _ = edit_paths(tmp_path, "Recolour it.\n\n## Pilot review\n\nKeep the collar ribbed.\n")
    assert kie.prompt_text(brief) == "Recolour it.\n\n\nKeep the collar ribbed."


def test_the_task_asks_for_the_2k_png_edit(
    kie: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: dict[str, Any] = {}

    def fake_call(_url: str, _key: str, data: bytes, _type: str) -> dict:
        sent.update(json.loads(data))
        return {"taskId": "t1"}

    monkeypatch.setattr(kie, "call", fake_call)
    kie.task_for("url", "Do it", tmp_path / "x.task", KEY)
    assert sent == {
        "model": "nano-banana-2-1",
        "input": {
            "prompt": "Do it",
            "image_input": ["url"],
            "aspect_ratio": "1:1",
            "resolution": "2K",
            "output_format": "png",
        },
    }


def test_an_upload_sends_the_file_and_returns_its_url(
    kie: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: dict[str, Any] = {}

    def fake_call(url: str, _key: str, data: bytes, content_type: str) -> dict:
        sent.update(url=url, data=data, content_type=content_type)
        return {"downloadUrl": "https://files/a.png"}

    monkeypatch.setattr(kie, "call", fake_call)
    photo = tmp_path / "photo.png"
    photo.write_bytes(b"the-bytes")

    assert kie.upload(photo, KEY) == "https://files/a.png"
    assert sent["url"] == kie.UPLOAD
    assert sent["content_type"].startswith("multipart/form-data; boundary=")
    assert b"the-bytes" in sent["data"]
    assert b'name="uploadPath"' in sent["data"]


def test_an_http_error_never_shows_the_key(
    kie: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(request: urllib.request.Request, timeout: int) -> None:
        assert timeout
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            Message(),
            io.BytesIO(b"bad key"),
        )

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    with pytest.raises(kie.KieError) as raised:
        kie.call(f"{kie.API}/chat/credit", KEY)
    assert KEY not in str(raised.value)
    assert "401" in str(raised.value)
