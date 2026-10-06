"""Native executable entry point; downloads exist only behind explicit setup."""

from __future__ import annotations

import argparse
import faulthandler
import hashlib
import json
import sys
from pathlib import Path

from .models import MODELS, Models
from .server import serve


def install_weights(root: Path) -> None:
    from huggingface_hub import HfApi, snapshot_download

    for checkpoint, _, revision in MODELS.values():
        info = HfApi().model_info(checkpoint, revision=revision, files_metadata=True)
        if info.sha != revision:
            raise ValueError("Checkpoint resolved to an unexpected revision")
        folder = root / revision
        snapshot_download(
            checkpoint,
            revision=revision,
            local_dir=folder,
            allow_patterns=["*.json", "*.txt", "*.fp16.safetensors"],
        )
        files = {}
        for sibling in info.siblings or []:
            name = sibling.rfilename
            if not name.endswith((".json", ".txt", ".fp16.safetensors")):
                continue
            path = folder / name
            if not path.is_file() or not path.resolve().is_relative_to(folder.resolve()):
                raise ValueError(f"Missing pinned weight file: {name}")
            data = path.read_bytes()
            if sibling.lfs is not None:
                if hashlib.sha256(data).hexdigest() != sibling.lfs.sha256:
                    raise ValueError(f"Weight integrity mismatch: {name}")
            elif (
                hashlib.sha1(b"blob " + str(len(data)).encode() + bytes([0]) + data).hexdigest()
                != sibling.blob_id
            ):
                raise ValueError(f"Checkpoint configuration integrity mismatch: {name}")
            files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        if not files or not any(name.endswith(".safetensors") for name in files):
            raise ValueError("Pinned checkpoint has no inference weights")
        (folder / "verified.json").write_text(
            json.dumps({"checkpoint": checkpoint, "revision": revision, "files": files}, indent=2),
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", required=True, type=Path)
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--install-weights", action="store_true")
    parser.add_argument("--capabilities", action="store_true")
    args = parser.parse_args()
    if args.install_weights:
        install_weights(args.weights)
        return
    backend = Models(args.weights)
    if args.capabilities:
        print(json.dumps(backend.capabilities()), flush=True)
        return
    if args.cache_root is None:
        parser.error("--cache-root is required for inference")
    faulthandler.dump_traceback_later(120, repeat=True)
    try:
        serve(backend, cache_root=str(args.cache_root))
    finally:
        faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Marigold worker: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
