"""Staging one ZIP (batch plan PR 7; spec *Accepted input*; ADR-0051).

Every archive is built here, entry by entry, with ``zipfile`` and hand-set
``ZipInfo`` fields -- traversal, absolute names, symlink mode bits, the
encrypted flag -- rather than kept as binary fixtures, so each test shows
exactly what is hostile about its archive. The seam is `stage_pngs`: what a
session holds afterwards, and that a refusal leaves nothing on disk.
"""

from __future__ import annotations

import random
import re
import warnings
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from etsy_listings.batches import StagingRefused, StagingStore, review, stage_pngs
from etsy_listings.batches import archive as archive_module
from etsy_listings.workspace.workspace import Workspace

from tests.support.batches import a_listing_template, png, uploads

NOW = datetime(2026, 9, 27, 11, 42, tzinfo=UTC)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    workspace = Workspace.discover(root_override=workspace_root)
    a_listing_template(workspace)
    return workspace


@pytest.fixture
def store(workspace: Workspace) -> StagingStore:
    return StagingStore(workspace)


def a_zip(*entries: tuple[str | zipfile.ZipInfo, bytes]) -> bytes:
    buffer = BytesIO()
    with warnings.catch_warnings():
        # Two entries with one name is a hostile archive some tests want.
        warnings.filterwarnings("ignore", "Duplicate name", UserWarning)
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in entries:
                archive.writestr(name, data)
    return buffer.getvalue()


def _stage(workspace: Workspace, store: StagingStore, *files: tuple[str, bytes]):  # noqa: ANN202
    return stage_pngs(workspace, store, "heavyweight-tee", uploads(*files), now=NOW)


def _staging_left(workspace: Workspace) -> list[Path]:
    directory = workspace.cache("staging")
    return sorted(directory.rglob("*")) if directory.is_dir() else []


class TestDiscovery:
    def test_every_png_at_any_depth_is_a_row_named_without_its_folders(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        archive = a_zip(
            ("Night Hike Club.png", png(1)),
            ("exports/Mountain Sunrise (1).png", png(2)),
            ("exports/autumn/deep/cedar-trail.png", png(3)),
        )

        session = _stage(workspace, store, ("kittl-export.zip", archive))

        rows = review(workspace, session).rows
        assert [(row.sources, row.name) for row in rows] == [
            (["Night Hike Club.png"], "night-hike-club"),
            (["exports/Mountain Sunrise (1).png"], "mountain-sunrise-1"),
            (["exports/autumn/deep/cedar-trail.png"], "cedar-trail"),
        ]
        assert all(row.state == "ready" for row in rows)

    def test_files_that_are_not_pngs_are_ignored_and_named(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        archive = a_zip(
            ("cedar-trail.png", png(1)),
            ("__MACOSX/._cedar-trail.png", b"\x00\x05\x16\x07 AppleDouble"),
            ("readme.txt", b"Exported with Kittl"),
            ("previews/", b""),
            ("previews/preview.jpg", b"\xff\xd8\xff\xe0 jpeg"),
        )

        session = _stage(workspace, store, ("kittl-export.zip", archive))

        assert [row.sources for row in session.rows] == [["cedar-trail.png"]]
        assert session.ignored == [
            "__MACOSX/._cedar-trail.png",
            "readme.txt",
            "previews/preview.jpg",
        ]

    def test_a_png_is_known_by_its_bytes_not_its_extension(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        archive = a_zip(("exports/lake-loop.dat", png(1)))

        session = _stage(workspace, store, ("kittl-export.zip", archive))

        (row,) = review(workspace, session).rows
        assert (row.sources, row.name, row.state) == (
            ["exports/lake-loop.dat"],
            "lake-loop",
            "ready",
        )

    def test_identical_pngs_in_one_zip_are_one_row_naming_both(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        archive = a_zip(("cedar-trail.png", png(1)), ("exports/cedar-trail copy.png", png(1)))

        session = _stage(workspace, store, ("kittl-export.zip", archive))

        (row,) = review(workspace, session).rows
        assert row.sources == ["cedar-trail.png", "exports/cedar-trail copy.png"]

    def test_the_zip_itself_is_not_kept(self, workspace: Workspace, store: StagingStore) -> None:
        session = _stage(workspace, store, ("kittl-export.zip", a_zip(("a.png", png(1)))))

        assert not workspace.staging_archive_file(session.id).exists()

    def test_the_default_label_leads_with_the_zips_name(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        """Spec, *Confirming a batch*: the ZIP's name is usually the
        collection the seller exported, so it leads the label."""
        session = _stage(workspace, store, ("Coding x Music.ZIP", a_zip(("a.png", png(1)))))

        assert re.fullmatch(
            r"Coding x Music · heavyweight-tee · \d{1,2} Sep \d\d:\d\d", session.label
        )

    def test_a_zip_named_with_folders_labels_by_its_file_name(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        session = _stage(
            workspace, store, ("C:\\exports\\kittl-export.zip", a_zip(("a.png", png(1))))
        )

        assert session.label.startswith("kittl-export · heavyweight-tee · ")


class TestInputMode:
    def test_two_zips_are_refused_with_nothing_on_disk(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        with pytest.raises(StagingRefused) as refused:
            _stage(
                workspace,
                store,
                ("autumn.zip", a_zip(("a.png", png(1)))),
                ("winter.zip", a_zip(("b.png", png(2)))),
            )

        assert refused.value.message == "These are 2 ZIPs, and a batch takes one."
        assert refused.value.remedy == (
            "Start a batch for each ZIP. Nothing was uploaded or changed."
        )
        assert _staging_left(workspace) == []

    def test_a_zip_with_loose_pngs_is_refused_with_nothing_on_disk(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        with pytest.raises(StagingRefused) as refused:
            _stage(
                workspace,
                store,
                ("lake-loop.png", png(1)),
                ("autumn.zip", a_zip(("a.png", png(2)))),
            )

        assert refused.value.message == (
            "These are a ZIP and loose files together, and a batch takes one or the other."
        )
        assert refused.value.remedy == (
            "Put the PNGs in the ZIP, or drop them without it. Nothing was uploaded or changed."
        )
        assert _staging_left(workspace) == []

    def test_a_file_that_is_not_a_zip_inside_is_refused(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, ("kittl-export.zip", b"PK\x03\x04 not really"))

        assert refused.value.message == "It is not a ZIP that can be read."
        assert _staging_left(workspace) == []

    def test_a_zip_with_no_pngs_is_refused(self, workspace: Workspace, store: StagingStore) -> None:
        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, ("kittl-export.zip", a_zip(("readme.txt", b"hi"))))

        assert refused.value.message == "It holds no PNG files."
        assert _staging_left(workspace) == []

    def test_26_unique_pngs_in_a_zip_are_refused_with_the_split_spelled_out(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        archive = a_zip(*[(f"d{n}.png", png(n)) for n in range(26)])

        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, ("kittl-export-autumn.zip", archive))

        # The staging-refused frame's own wording (UI doc §4).
        assert refused.value.message == (
            "It holds 26 different PNG designs, and a batch takes at most 25."
        )
        assert refused.value.remedy == (
            "Split the export into two ZIPs and start a batch for each. "
            "Nothing was uploaded or changed."
        )
        assert _staging_left(workspace) == []


def _info(name: str, **fields: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 9, 27, 11, 42, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    for field, value in fields.items():
        setattr(info, field, value)
    return info


def _encrypted(name: str, data: bytes) -> bytes:
    """An entry whose general-purpose flag says it is encrypted. `zipfile`
    cannot write encryption, so the flag is set on the central directory
    record it writes on close, which is the one a reader goes by."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(_info(name), data)
        archive.filelist[-1].flag_bits |= 0x1
    return buffer.getvalue()


UNSAFE_REMEDY = (
    "Export it again, or unzip it and drop the PNGs themselves. Nothing was uploaded or changed."
)


class TestUnsafeArchives:
    """Each archive holds one good PNG first, so a refusal is seen to leave
    even that one behind (ADR-0051: any refusal leaves nothing on disk)."""

    @pytest.mark.parametrize(
        ("entry", "problem"),
        [
            ("../escape.png", "points outside the ZIP"),
            ("exports/../../escape.png", "points outside the ZIP"),
            ("/etc/escape.png", "is an absolute path"),
            ("\\escape.png", "is an absolute path"),
            ("C:/escape.png", "is an absolute path"),
            ("exports\\..\\escape.png", "points outside the ZIP"),
        ],
    )
    def test_a_name_that_leaves_the_archive_is_refused(
        self, workspace: Workspace, store: StagingStore, entry: str, problem: str
    ) -> None:
        info = _info(entry)
        archive = a_zip(("good.png", png(1)), (info, png(2)))

        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, ("kittl-export.zip", archive))

        # The name as `zipfile` reports it, which on Windows has its
        # backslashes turned into slashes; refused either way.
        message = f"{info.filename} inside it {problem}."
        assert (refused.value.message, refused.value.remedy) == (message, UNSAFE_REMEDY)
        assert _staging_left(workspace) == []

    def test_a_symlink_is_refused(self, workspace: Workspace, store: StagingStore) -> None:
        link = _info("exports/link.png", create_system=3, external_attr=0o120777 << 16)
        archive = a_zip(("good.png", png(1)), (link, b"/etc/passwd"))

        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, ("kittl-export.zip", archive))

        assert refused.value.message == "exports/link.png inside it is a symbolic link."
        assert _staging_left(workspace) == []

    def test_an_entry_that_is_not_a_plain_file_is_refused(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        fifo = _info("exports/pipe", create_system=3, external_attr=0o010644 << 16)
        archive = a_zip(("good.png", png(1)), (fifo, b""))

        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, ("kittl-export.zip", archive))

        assert refused.value.message == "exports/pipe inside it is not a plain file."
        assert _staging_left(workspace) == []

    def test_an_ordinary_unix_file_is_accepted(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        plain = _info("lake-loop.png", create_system=3, external_attr=0o100644 << 16)

        session = _stage(workspace, store, ("kittl-export.zip", a_zip((plain, png(1)))))

        assert [row.sources for row in session.rows] == [["lake-loop.png"]]

    def test_an_encrypted_entry_is_refused(self, workspace: Workspace, store: StagingStore) -> None:
        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, ("kittl-export.zip", _encrypted("secret.png", png(1))))

        assert refused.value.message == "secret.png inside it is encrypted."
        assert refused.value.remedy == (
            "Export it again without a password, or unzip it and drop the PNGs themselves. "
            "Nothing was uploaded or changed."
        )
        assert _staging_left(workspace) == []

    @pytest.mark.parametrize(
        "twin", ["exports/lake-loop.png", "exports/Lake-Loop.png", "exports//./lake-loop.png"]
    )
    def test_two_entries_with_one_name_are_refused(
        self, workspace: Workspace, store: StagingStore, twin: str
    ) -> None:
        archive = a_zip(("exports/lake-loop.png", png(1)), (_info(twin), png(2)))

        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, ("kittl-export.zip", archive))

        assert refused.value.message == f"{twin} appears in it twice."
        assert _staging_left(workspace) == []

    def test_more_than_2000_entries_are_refused(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        archive = a_zip(("good.png", png(1)), *[(f"notes/{n}.txt", b"") for n in range(2000)])

        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, ("kittl-export.zip", archive))

        assert refused.value.message == "It holds 2001 entries, and a ZIP can hold at most 2000."
        assert _staging_left(workspace) == []

    def test_an_entry_that_expands_more_than_100_times_is_refused(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        # A PNG signature and then 8 MiB of zeros: deflate packs it about
        # a thousandfold, which is what a ZIP bomb looks like.
        bomb = PNG_SIGNATURE + bytes(8 * 2**20)
        archive = a_zip(("good.png", png(1)), ("bomb.png", bomb))

        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, ("kittl-export.zip", archive))

        assert refused.value.message == (
            "bomb.png inside it unpacks to more than 100 times its packed size."
        )
        assert _staging_left(workspace) == []

    def test_a_zip_that_unpacks_past_the_total_is_refused(
        self, workspace: Workspace, store: StagingStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(archive_module, "MAX_EXPANDED_BYTES", len(png(1)) + 10)
        archive = a_zip(("a.png", png(1)), ("b.png", png(2)))

        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, ("kittl-export.zip", archive))

        assert refused.value.message.startswith("It unpacks to more than ")
        assert _staging_left(workspace) == []

    def test_a_zip_over_the_compressed_limit_is_refused(
        self, workspace: Workspace, store: StagingStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(archive_module, "MAX_ARCHIVE_BYTES", 100)
        archive = a_zip(("a.png", png(1)))

        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, ("kittl-export.zip", archive))

        assert refused.value.message.startswith("It is larger than ")
        assert _staging_left(workspace) == []


class TestDamagedArchives:
    def test_an_entry_whose_bytes_fail_their_checksum_is_refused(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        # Noise, so the entry is larger than the first read `zipfile` makes
        # and its checksum fails while it is being stored, not when it is
        # first opened.
        noise = Image.frombytes("RGBA", (64, 64), random.Random(7).randbytes(64 * 64 * 4))
        encoded = BytesIO()
        noise.save(encoded, format="PNG")
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("good.png", png(1))
            archive.writestr("damaged.png", encoded.getvalue())
        data = bytearray(buffer.getvalue())
        data[data.rindex(b"IEND") - 100] ^= 0xFF

        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, ("kittl-export.zip", bytes(data)))

        assert refused.value.message == "damaged.png inside it cannot be read."
        assert _staging_left(workspace) == []

    def test_a_small_damaged_entry_is_refused_when_it_is_first_opened(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("damaged.png", png(1))
        data = bytearray(buffer.getvalue())
        data[data.index(b"IEND") + 5] ^= 0xFF

        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, ("kittl-export.zip", bytes(data)))

        assert refused.value.message == "damaged.png inside it cannot be read."
        assert _staging_left(workspace) == []

    def test_a_compression_method_zipfile_lacks_is_refused(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("odd.png", png(1))
            archive.filelist[-1].compress_type = 99
        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, ("kittl-export.zip", buffer.getvalue()))

        assert refused.value.message == "odd.png inside it cannot be read."
        assert _staging_left(workspace) == []
