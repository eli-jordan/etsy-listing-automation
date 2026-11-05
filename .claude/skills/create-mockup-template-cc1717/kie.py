"""Nano Banana 2.1 2K edits through Kie.ai.

edit: apply one brief to one image.
colours: generate a run's colours from its briefs: the named slugs, or every colour
with no out/ photo.

A task's ID waits beside its photo until the photo is saved, so a rerun collects a task
that outlived its first run instead of paying for a new one.

Run from the repo root:
  uv run python .claude/skills/create-mockup-template-cc1717/kie.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PIL import Image

API = "https://api.kie.ai/api/v1"
UPLOAD = "https://kieai.redpandaai.co/api/file-stream-upload"
MODEL = "nano-banana-2-1"
CREDITS_PER_IMAGE = 6  # at 2K
CONCURRENCY = 10
AGENT = "create-mockup-template/1.0"
POLL_SECONDS = 5
TASK_TIMEOUT_SECONDS = 660  # Kie.ai ends a task at 10 minutes
RETRY_SECONDS = (2, 5, 15, 30)
WORKSPACE = os.environ.get(
    "ETSY_API_WORKSPACE", r"C:\Users\Admin\iCloudDrive\naturally-inked-studio-workspace"
)
WORKSPACE_ENV = Path(WORKSPACE) / ".env"
OUT_OF_CREDITS = "Kie.ai is out of credits"
SUCCESS = 200  # failures arrive as HTTP 200 with another `code` in the body
NO_CREDITS = 402
RATE_LIMITED = 429
SERVER_ERROR = 500


class KieError(Exception):
    pass


class TransientError(KieError):
    """Worth trying again: the request may never have been acted on."""


class RateLimitedError(TransientError):
    """Refused outright, so even a request that isn't idempotent is safe to repeat."""


def say(message: str) -> None:
    sys.stdout.write(f"{message}\n")
    sys.stdout.flush()


def api_key() -> str:
    key = os.environ.get("KIE_API_KEY")
    if not key and WORKSPACE_ENV.is_file():
        for line in WORKSPACE_ENV.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "KIE_API_KEY":
                key = value.strip().strip("\"'")
    if not key:
        raise SystemExit(f"Set KIE_API_KEY in the environment or {WORKSPACE_ENV}.")
    return key


def failure(code: object, message: str) -> KieError:
    if code == NO_CREDITS:
        return KieError(f"{OUT_OF_CREDITS}: {message}")
    if code == RATE_LIMITED:
        return RateLimitedError(message)
    if isinstance(code, int) and code >= SERVER_ERROR:
        return TransientError(message)
    return KieError(message)


def fetch(request: urllib.request.Request) -> bytes:
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return bytes(response.read())
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")[:500]
        raise failure(error.code, f"HTTP {error.code} from {request.full_url}: {body}") from None
    except (OSError, http.client.HTTPException) as error:
        raise TransientError(f"{request.full_url}: {error!r}") from None


def call(url: str, key: str, data: bytes | None = None, content_type: str = "") -> Any:
    headers = {"Authorization": f"Bearer {key}", "User-Agent": AGENT}
    if data is not None:
        headers["Content-Type"] = content_type
    body = fetch(urllib.request.Request(url, data, headers))
    try:
        payload = json.loads(body)
    except ValueError:
        raise TransientError(f"{url}: unreadable response") from None
    code = payload.get("code") if isinstance(payload, dict) else None
    if code != SUCCESS:
        message = payload.get("msg") if isinstance(payload, dict) else payload
        raise failure(code, f"{url}: {code} {message}")
    if payload.get("data") is None:
        raise TransientError(f"{url}: empty response")
    return payload["data"]


def retrying(action: Callable[[], Any], retry_on: type[KieError] = TransientError) -> Any:
    for delay in RETRY_SECONDS:
        try:
            return action()
        except retry_on:
            time.sleep(delay)
    return action()


def balance(key: str) -> float:
    return float(retrying(lambda: call(f"{API}/chat/credit", key)))


def require_credits(key: str, targets: list[str]) -> None:
    needed = len(targets) * CREDITS_PER_IMAGE
    available = balance(key)
    if available < needed:
        raise KieError(
            f"{OUT_OF_CREDITS}: {available:g} left, {needed} needed.\n"
            f"Not generated: {', '.join(targets)}"
        )


def failure_message(failures: list[str], key: str) -> str:
    lines = "\n".join(failures)
    try:
        empty = balance(key) < CREDITS_PER_IMAGE
    except KieError:
        return lines
    return f"{OUT_OF_CREDITS}.\n{lines}" if empty else lines


def upload(path: Path, key: str) -> str:
    boundary = uuid.uuid4().hex
    name = f"{uuid.uuid4().hex}{path.suffix.lower()}"
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    body = io.BytesIO()
    for field, value in (("uploadPath", "mockup-recolours"), ("fileName", name)):
        disposition = f'Content-Disposition: form-data; name="{field}"'
        body.write(f"--{boundary}\r\n{disposition}\r\n\r\n{value}\r\n".encode())
    disposition = f'Content-Disposition: form-data; name="file"; filename="{name}"'
    body.write(f"--{boundary}\r\n{disposition}\r\nContent-Type: {mime}\r\n\r\n".encode())
    body.write(path.read_bytes())
    body.write(f"\r\n--{boundary}--\r\n".encode())
    content_type = f"multipart/form-data; boundary={boundary}"
    uploaded = retrying(lambda: call(UPLOAD, key, body.getvalue(), content_type))
    return str(uploaded["downloadUrl"])


def prompt_text(brief: Path) -> str:
    """The brief without the headings that file its review notes."""
    lines = brief.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.startswith("## ")).strip()


def result_url(data: dict[str, Any]) -> str:
    try:
        return str(json.loads(data["resultJson"])["resultUrls"][0])
    except (KeyError, IndexError, TypeError, ValueError):
        raise KieError(f"task {data.get('taskId')}: no image in its result") from None


def finished_url(task_id: str, key: str) -> str:
    deadline = time.monotonic() + TASK_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            data = call(f"{API}/jobs/recordInfo?taskId={task_id}", key)
        except TransientError:
            data = {}
        if data.get("state") == "success":
            return result_url(data)
        if data.get("state") == "fail":
            raise KieError(f"task {task_id}: {data.get('failCode')} {data.get('failMsg')}")
        time.sleep(POLL_SECONDS)
    raise TransientError(
        f"task {task_id} unfinished after {TASK_TIMEOUT_SECONDS}s; rerun to collect it"
    )


def task_for(image_url: str, prompt: str, ticket: Path, key: str) -> str:
    """The task for this prompt: one an earlier run left waiting, or a new one."""
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    if ticket.is_file():
        saved, _, task_id = ticket.read_text(encoding="utf-8").partition(" ")
        if saved == digest:
            return task_id
    task = {
        "model": MODEL,
        "input": {
            "prompt": prompt,
            "image_input": [image_url],
            "aspect_ratio": "1:1",
            "resolution": "2K",
            "output_format": "png",
        },
    }
    body = json.dumps(task).encode()
    created = retrying(
        lambda: call(f"{API}/jobs/createTask", key, body, "application/json"), RateLimitedError
    )
    task_id = str(created["taskId"])
    ticket.write_text(f"{digest} {task_id}", encoding="utf-8")
    return task_id


def keep_previous(output: Path) -> None:
    if output.exists():
        rounds = len(list(output.parent.glob(f"{output.stem}-round*.keep")))
        output.replace(output.with_name(f"{output.stem}-round{rounds + 1}.keep"))


def generate(image_url: str, brief: Path, output: Path, key: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    ticket = output.with_suffix(".task")
    try:
        url = finished_url(task_for(image_url, prompt_text(brief), ticket, key), key)
        request = urllib.request.Request(url, headers={"User-Agent": AGENT})
        raw = retrying(lambda: fetch(request))
    except TransientError:
        raise
    except KieError:
        ticket.unlink(missing_ok=True)
        raise
    with Image.open(io.BytesIO(raw)) as image:
        photo = image.convert("RGB")
    keep_previous(output)
    photo.save(output, "PNG")
    ticket.unlink(missing_ok=True)


def edit(args: argparse.Namespace) -> None:
    key = api_key()
    require_credits(key, [args.output])
    try:
        generate(upload(Path(args.image), key), Path(args.brief), Path(args.output), key)
    except (KieError, OSError) as error:
        sys.exit(failure_message([str(error)], key))
    say(args.output)


def pending(run_dir: Path) -> list[str]:
    briefs = sorted((run_dir / "briefs").glob("*.md"))
    return [brief.stem for brief in briefs if not (run_dir / "out" / f"{brief.stem}.png").exists()]


def colours(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    slugs = args.slugs or pending(run_dir)
    if not slugs:
        say("Nothing to generate: every colour has a photo. Name slugs to regenerate.")
        return
    key = api_key()
    require_credits(key, slugs)
    source_url = upload(run_dir / "source.png", key)

    def run(slug: str) -> str | None:
        brief = run_dir / "briefs" / f"{slug}.md"
        try:
            generate(source_url, brief, run_dir / "out" / f"{slug}.png", key)
        except (KieError, OSError) as error:
            return f"{slug}: {error}"
        say(slug)
        return None

    with ThreadPoolExecutor(CONCURRENCY) as pool:
        failures = [failure for failure in pool.map(run, slugs) if failure]
    if failures:
        sys.exit(failure_message(failures, key))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    one = commands.add_parser("edit", help="apply one brief to one image")
    one.add_argument("image")
    one.add_argument("brief")
    one.add_argument("output")
    one.set_defaults(func=edit)

    many = commands.add_parser("colours", help="generate a run's colours from its briefs")
    many.add_argument("run_dir")
    many.add_argument("slugs", nargs="*", help="colours to regenerate; default: those missing")
    many.set_defaults(func=colours)

    args = parser.parse_args()
    try:
        args.func(args)
    except KieError as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
