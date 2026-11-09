"""SEO review of Etsy listings: score terms, validate a plan, build the report, apply decisions.

Run from the repo root:

    uv run python .claude/skills/etsy-listings-optimize-seo/seo_review.py COMMAND RUN ...

RUN is a folder name under the review home, such as christmas-2026-11-06. The
home holds one keyword store and one competition store shared by every run, so
eRank figures already paid for are reused. See SKILL.md for the order of steps.

Only `write --write` changes anything, and it changes listing.yaml alone.
"""

from __future__ import annotations

import argparse
import base64
import collections
import copy
import fnmatch
import functools
import html
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from etsy_listings.core.clients.etsy.transport import Transport
from etsy_listings.core.connections import _etsy_app_key_source
from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.workspace import Workspace

HERE = Path(__file__).resolve().parent
WORKSPACE = Path(
    os.environ.get(
        "ETSY_API_WORKSPACE", r"C:\Users\Admin\iCloudDrive\naturally-inked-studio-workspace"
    )
)
HOME = Path(os.environ.get("ETSY_SEO_HOME", r"C:\Users\Admin\Downloads\etsy-seo-review"))
KEYWORDS = HOME / "keyword-store.json"
COMPETITION = HOME / "competition-store.json"
SUGGESTIONS = HOME / "suggestion-store.json"
LISTINGS_PATH = "/v3/application/listings/active"
BATCH_PATH = "/v3/application/listings/batch"
TSHIRT_TAXONOMY = 482
COMPETITION_MAX_AGE_DAYS = 14
SUGGESTION_MAX_AGE_DAYS = 14
SECONDS_PER_SUGGESTION = 9
SUGGESTION_ROW_FIELDS = 4
HIGH_SEARCHES = 100
TAG_LIMIT, TITLE_LIMIT, TAG_COUNT, LEAD_WINDOW = 20, 140, 13, 160
MIN_SHARED_LISTINGS = 6
AUDIT_ROW_FIELDS = 6
AUDIT_HEADER_FIELDS = 3
GOOD_TIERS = ("sweet", "small", "busy")
SHIRT_WORDS = re.compile(r"\b(t-?shirts?|tees?|tshirts?|shirts?)\b", re.IGNORECASE)
# Suggestions a tee shop can't serve: digital files, other products, other garments.
OFF_INTENT = re.compile(
    r"\b(png|svg|dxf|pdf|mockups?|digital|printable|clipart|template|pattern|stickers?|decals?"
    r"|mugs?|tumblers?|ornaments?|decor|wreaths?|signs?|cards?|costumes?|masks?|pins?|earrings?"
    r"|necklaces?|socks|hats?|blankets?|pajamas?|hoodies?|sweatshirts?|sweaters?|crewnecks?"
    r"|kids|toddler|baby|onesie|custom|personali[sz]ed)\b",
    re.IGNORECASE,
)

# The seller's niche test: shirt searches a month, competing tees, shirt share.
WRONG_SHARE, MEASURED_FLOOR = 15, 20
SWEET_SEARCHES, SWEET_TEES = 30, 12000
SMALL_SEARCHES, SMALL_TEES = 10, 5000
OPEN_TEES, OPEN_SHARE = 4000, 14
BUSY_SEARCHES, BUSY_TEES = 100, 50000
CROWDED_LISTINGS = 100000

Json = dict[str, Any]


def say(*parts: object) -> None:
    sys.stdout.write(" ".join(str(p) for p in parts) + "\n")
    sys.stdout.flush()


def current_date() -> date:
    return datetime.now(UTC).date()


def load(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf8")) if path.exists() else default


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf8")


def number(value: str) -> int | None:
    value = value.replace(",", "").replace("%", "").strip()
    return int(value) if value.isdigit() else None


def workspace() -> tuple[Workspace, ListingDocuments]:
    ws = Workspace.discover(root_override=WORKSPACE)
    return ws, ListingDocuments(ws)


def transport() -> Transport:
    return Transport(_etsy_app_key_source(WORKSPACE))


def run_dir(name: str) -> Path:
    return HOME / name


def scoped(run: Path) -> list[Json]:
    listings = load(run / "listings.json", None)
    if listings is None:
        sys.exit("run `scope` first")
    return listings


def tags_of(doc: Json) -> list[str]:
    """A listing's tags; a new listing has none yet."""
    return list(doc["etsy"].get("tags") or [])


def title_of(doc: Json) -> str:
    return doc["etsy"].get("title") or ""


def title_terms(title: str) -> list[str]:
    return [t.strip() for t in html.unescape(title).split(",")][:2]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def tier_of(count: int, est: int, tees: int, share: int) -> str:
    wrong = tees > 0 and share < WRONG_SHARE and count >= MEASURED_FLOOR
    rules = (
        (tees == 0, "open"),
        (wrong, "wrong"),
        (est >= SWEET_SEARCHES and tees <= SWEET_TEES, "sweet"),
        (est >= SMALL_SEARCHES and tees <= SMALL_TEES, "small"),
        (est < SMALL_SEARCHES and tees <= OPEN_TEES and share >= OPEN_SHARE, "open"),
        (est >= BUSY_SEARCHES and tees <= BUSY_TEES, "busy"),
    )
    return next((tier for matched, tier in rules if matched), "crowded")


@functools.cache
def suggestions() -> Json:
    return load(SUGGESTIONS, {})


@functools.cache
def suggested_phrases() -> frozenset[str]:
    """Every phrase autocomplete has offered, including under other seeds."""
    stored = suggestions()
    offered = {t.lower() for e in stored.values() for t in e["list"]}
    return frozenset(offered | {t for t, e in stored.items() if e["hit"]})


def confirmed(term: str) -> bool | None:
    """Whether Etsy autocomplete offers this exact term. None until it's been checked."""
    if term.lower() in suggested_phrases():
        return True
    entry = suggestions().get(term.lower())
    return None if entry is None else False


def info(term: str, words: Json, rivals: Json) -> Json:
    """Score one term with the seller's niche test."""
    word = words.get(term.lower()) or {}
    rival = rivals.get(term.lower())
    searches = word.get("s")
    count = searches if isinstance(searches, int) else 0
    keys = ("comp", "last", "lastMonth", "peak", "peakMonth")
    out = {"s": searches, "tees": None, "share": None, "est": None} | {k: word.get(k) for k in keys}
    out["confirmed"] = confirmed(term)
    if rival:
        est = round(count * rival["share"] / 100)
        out |= {"tees": rival["tees"], "share": rival["share"], "est": est}
        out["tier"] = tier_of(count, est, rival["tees"], rival["share"])
    else:
        out["tier"] = "crowded" if (out["comp"] or 0) > CROWDED_LISTINGS else "design"
    return out


def stores() -> tuple[Json, Json]:
    return load(KEYWORDS, {}), load(COMPETITION, {})


def reach(tags: list[str], words: Json, rivals: Json) -> int:
    scores = (info(t, words, rivals) for t in tags)
    return sum(s["est"] or 0 for s in scores if s["tier"] in GOOD_TIERS)


def weak(score: Json) -> bool:
    return not isinstance(score["s"], int) or score["s"] < MEASURED_FLOOR


def listing_names(root: Path, patterns: list[str]) -> list[str]:
    folders = [p for p in root.iterdir() if (p / "listing.yaml").exists()]
    matched = [p.name for p in folders if any(fnmatch.fnmatch(p.name, x) for x in patterns)]
    return sorted(matched)


def lock_listing_id(folder: Path) -> int | None:
    lock = folder / "state.lock.json"
    text = lock.read_text(encoding="utf8") if lock.exists() else ""
    found = re.search(r'"(?:etsy_)?listing_id"\s*:\s*"?(\d+)', text)
    return int(found.group(1)) if found else None


def listing_states(ids: list[int]) -> dict[int, str]:
    client = transport()
    states: dict[int, str] = {}
    for start in range(0, len(ids), 100):
        batch = ",".join(str(i) for i in ids[start : start + 100])
        body = client.get(BATCH_PATH, params=[("listing_ids", batch)]).json()
        states |= {x["listing_id"]: x["state"] for x in body["results"]}
    return states


def cmd_scope(args: argparse.Namespace) -> None:
    """Record which listings this run covers, from glob patterns on listing folder names."""
    ws, docs = workspace()
    root = ws.listing_file("x").parent.parent
    names = listing_names(root, args.patterns)
    rows = [{"dir": n, "id": lock_listing_id(root / n)} for n in names]
    states = listing_states([r["id"] for r in rows if r["id"]])
    for row in rows:
        live = states.get(row["id"]) == "active"
        row["state"] = "Live" if live else ("Draft" if row["id"] else "New")
        doc = docs.read(row["dir"])
        say(f"{row['state']:5} {row['id']} {row['dir']}")
        say("     ", title_of(doc) or "(no title yet)")
        say("      brief:", str(doc.get("brief"))[:160].replace("\n", " "))
    save(run_dir(args.run) / "listings.json", rows)
    say(f"{len(rows)} listings, {sum(r['state'] == 'Live' for r in rows)} live")


def fetch_niche(path: Path, queries: list[str]) -> Json:
    seen = load(path, {})
    client = transport()
    for query in queries:
        if query in seen:
            continue
        params = [
            ("keywords", query),
            ("sort_on", "score"),
            ("limit", "100"),
            ("taxonomy_id", str(TSHIRT_TAXONOMY)),
        ]
        body = client.get(LISTINGS_PATH, params=params).json()
        rows = [
            {"id": x["listing_id"], "title": html.unescape(x["title"]), "tags": x["tags"]}
            for x in body["results"]
        ]
        seen[query] = {"count": body["count"], "rows": rows}
        save(path, seen)
        time.sleep(0.3)
    return seen


def new_tags(row: Json, unknown: dict[str, int], covered: set[str]) -> list[str]:
    tags = {t.lower() for t in row["tags"]}
    return [t for t in tags if t in unknown and t not in covered]


def audit_picks(seen: Json, unknown: dict[str, int], limit: int) -> None:
    pool = {r["id"]: r | {"query": q} for q, b in seen.items() for r in b["rows"]}
    covered: set[str] = set()
    for _ in range(min(limit, len(pool))):
        best = max(
            pool.values(), key=lambda r: sum(unknown[t] for t in new_tags(r, unknown, covered))
        )
        gain = new_tags(best, unknown, covered)
        if not gain:
            break
        covered |= set(gain)
        del pool[best["id"]]
        say(best["id"], f"[{best['query']}]", gain)


def cmd_niche(args: argparse.Namespace) -> None:
    """Top tees per buyer query, their shared tags, and which listings to audit to price them."""
    seen = fetch_niche(run_dir(args.run) / "niche.json", args.queries)
    words, _ = stores()
    weight: collections.Counter[str] = collections.Counter()
    for query, block in seen.items():
        counts = collections.Counter(t.lower() for r in block["rows"] for t in set(r["tags"]))
        weight.update(counts)
        top = counts.most_common(18)
        say(f"== {query} ({block['count']:,} tees)")
        say(", ".join(f"{t}:{n}{'' if t in words else '?'}" for t, n in top))
    skip = re.compile(args.skip)
    unknown = {
        t: n
        for t, n in weight.items()
        if t not in words and n >= MIN_SHARED_LISTINGS and not skip.search(t)
    }
    say(f"\n{len(unknown)} unpriced tags (marked ?). Audit picks, most useful first:")
    audit_picks(seen, unknown, args.picks)


def audit_header_month(line: str, month: str | None) -> str | None:
    parts = [p.strip() for p in line.split("|")]
    return parts[2] if len(parts) >= AUDIT_HEADER_FIELDS and parts[2] else month


def audit_row(fields: list[str], month: str | None) -> Json:
    searches = number(fields[2])
    if searches is None:
        searches = "<20" if "<" in fields[2] else 0
    return {
        "s": searches,
        "comp": number(fields[5]),
        "last": number(fields[1]),
        "lastMonth": month,
        "seen": str(current_date()),
        "src": "audit",
    }


def cmd_ingest(args: argparse.Namespace) -> None:
    """Merge audits.txt rows from extract_audit_rows.js into the keyword store."""
    text = (run_dir(args.run) / "audits.txt").read_text(encoding="utf8")
    words = load(KEYWORDS, {})
    month, added = None, 0
    for line in text.splitlines():
        fields = line.split("|")
        if line.startswith("#"):
            month = audit_header_month(line, month)
        elif len(fields) >= AUDIT_ROW_FIELDS:
            key = fields[0].strip().lower()
            words[key] = (words.get(key) or {}) | audit_row(fields, month)
            added += 1
    save(KEYWORDS, words)
    say(f"{added} rows merged, {len(words)} terms in the store")


def read_terms(file: str) -> list[str]:
    lines = Path(file).read_text(encoding="utf8").splitlines()
    return [t.strip().lower() for t in lines if t.strip()]


def competition_of(client: Transport, term: str) -> Json:
    common = [("keywords", term), ("sort_on", "score")]
    wide = client.get(LISTINGS_PATH, params=[*common, ("limit", "100")]).json()
    tee_filter = [("limit", "1"), ("taxonomy_id", str(TSHIRT_TAXONOMY))]
    tees = client.get(LISTINGS_PATH, params=[*common, *tee_filter]).json()
    results = wide.get("results", [])
    shirts = sum(
        1
        for x in results
        if x.get("taxonomy_id") == TSHIRT_TAXONOMY or SHIRT_WORDS.search(x["title"])
    )
    return {
        "all": wide["count"],
        "tees": tees["count"],
        "share": round(100 * shirts / max(1, len(results))),
        "seen": str(current_date()),
    }


def wanted_terms(run: Path, file: str | None) -> set[str]:
    _, docs = workspace()
    plan = load(run / "plan.json", {})
    terms = {s[1].lower() for entry in plan.values() for s in entry.get("swaps", [])}
    terms |= {t.lower() for entry in plan.values() for t in entry.get("tags", [])}
    for row in scoped(run):
        terms |= {t.lower() for t in tags_of(docs.read(row["dir"]))}
    return terms | set(read_terms(file) if file else [])


def is_fresh(entry: Json, days: int = COMPETITION_MAX_AGE_DAYS) -> bool:
    age = current_date() - date.fromisoformat(entry["seen"])
    return age.days <= days


def cmd_competition(args: argparse.Namespace) -> None:
    """Fetch competing tees and shirt share for scoped tags, planned tags and terms in FILE."""
    terms = wanted_terms(run_dir(args.run), args.file)
    rivals = load(COMPETITION, {})
    todo = sorted(t for t in terms if t not in rivals or not is_fresh(rivals[t]))
    say(f"{len(terms)} terms, {len(todo)} to fetch")
    client = transport()
    for index, term in enumerate(todo):
        rivals[term] = competition_of(client, term)
        if index % 10 == 0:
            save(COMPETITION, rivals)
            say(index, term, rivals[term])
        time.sleep(0.25)
    save(COMPETITION, rivals)
    say("done")


def score_line(term: str, s: Json, width: int) -> str:
    peak = f" peak={s['peak']} {s['peakMonth']}" if s["peak"] else ""
    numbers = f"s={s['s']} est={s['est']} tees={s['tees']} share={s['share']}"
    known = {True: "confirmed", False: "unconfirmed", None: "unchecked"}[s["confirmed"]]
    return f"{term:{width}} {s['tier']:8} {known:11} {numbers}{peak}"


def cmd_score(args: argparse.Namespace) -> None:
    """Print every scoped tag with its tier, or rank the terms in FILE."""
    words, rivals = stores()
    if args.file:
        rows = [(t, info(t, words, rivals)) for t in read_terms(args.file)]
        for term, s in sorted(rows, key=lambda r: -(r[1]["est"] or 0)):
            say(score_line(term, s, 26))
        return
    _, docs = workspace()
    tally: collections.Counter[str] = collections.Counter()
    under = total = 0
    for row in scoped(run_dir(args.run)):
        say(f"## {row['dir']} ({row['state']})")
        for tag in tags_of(docs.read(row["dir"])):
            s = info(tag, words, rivals)
            tally[s["tier"]] += 1
            total += 1
            under += weak(s)
            say("  ", score_line(tag, s, 22))
    say(dict(tally), f"{under} of {total} tags under 20 searches or unmeasured")


def cmd_suggest(args: argparse.Namespace) -> None:
    """Write RUN/suggest_batch.js for scoped tags, planned tags and terms in FILE."""
    run = run_dir(args.run)
    stored = load(SUGGESTIONS, {})
    terms = wanted_terms(run, args.file)
    todo = sorted(
        t for t in terms if t not in stored or not is_fresh(stored[t], SUGGESTION_MAX_AGE_DAYS)
    )
    template = (HERE / "extract_suggestions.js").read_text(encoding="utf8")
    script = template.replace('"__TERMS__"', json.dumps(todo, ensure_ascii=False))
    (run / "suggest_batch.js").write_text(script, encoding="utf8")
    minutes = round(len(todo) * SECONDS_PER_SUGGESTION / 60)
    say(f"{len(terms)} terms, {len(todo)} to check, about {minutes} minutes")
    say(run / "suggest_batch.js")


def suggestion_row(line: str) -> tuple[str, Json] | None:
    fields = line.split("|")
    if line.startswith("#") or len(fields) < SUGGESTION_ROW_FIELDS:
        return None
    found = [x for x in fields[3].split(";") if x]
    entry = {"hit": fields[1] == "1", "n": int(fields[2]), "list": found}
    return fields[0].strip().lower(), entry | {"seen": str(current_date())}


def cmd_ingest_suggestions(args: argparse.Namespace) -> None:
    """Merge RUN/suggestions.txt, the rows from suggest_batch.js, into the suggestion store."""
    text = (run_dir(args.run) / "suggestions.txt").read_text(encoding="utf8")
    rows = [row for row in map(suggestion_row, text.splitlines()) if row]
    stored = load(SUGGESTIONS, {}) | dict(rows)
    save(SUGGESTIONS, stored)
    hits = sum(entry["hit"] for _, entry in rows)
    say(f"{len(rows)} rows merged, {hits} confirmed, {len(stored)} terms in the store")


def related_terms(run: Path) -> collections.Counter[str]:
    path = run / "related.txt"
    lines = path.read_text(encoding="utf8").splitlines() if path.exists() else []
    return collections.Counter(t.strip().lower() for t in lines if t.strip() and t[0] != "#")


def wanted_by_shop(term: str) -> bool:
    return bool(not OFF_INTENT.search(term) and len(term.split()) > 1)


def cmd_discover(args: argparse.Namespace) -> None:
    """Rank unpriced suggestions and related searches a tee shop could use, into candidates.txt."""
    run = run_dir(args.run)
    words, _ = stores()
    stored = load(SUGGESTIONS, {})
    found: collections.Counter[str] = related_terms(run)
    for entry in stored.values():
        found.update(t.lower() for t in entry["list"])
    fresh = {
        t: n for t, n in found.items() if t not in stored and t not in words and wanted_by_shop(t)
    }
    top = sorted(fresh, key=lambda t: (-fresh[t], not SHIRT_WORDS.search(t), t))[: args.limit]
    (run / "candidates.txt").write_text("\n".join(top) + "\n", encoding="utf8")
    say(f"{len(found)} phrases seen, {len(fresh)} new and usable, top {len(top)} saved:")
    say(" | ".join(f"{t} ({fresh[t]})" for t in top[:60]))


def searches_band(searches: int | str | None) -> str:
    if searches is None:
        return "no eRank data"
    if searches in (0, "<20"):
        return "under 20" if searches else "none measured"
    return "100 or more" if searches >= HIGH_SEARCHES else "20 to 99"


def share_table(title: str, rows: dict[str, list[bool]]) -> None:
    say(f"\n{title}")
    for key, marks in sorted(rows.items(), key=lambda r: -len(r[1])):
        hits = sum(marks)
        say(f"  {key:18} {hits:4} of {len(marks):4} confirmed ({round(100 * hits / len(marks))}%)")


def grouped(checked: Json, key: Any) -> dict[str, list[bool]]:
    rows: dict[str, list[bool]] = collections.defaultdict(list)
    for score in checked.values():
        rows[key(score)].append(score["confirmed"])
    return rows


def scoped_tags(run: Path) -> set[str]:
    _, docs = workspace()
    return {t.lower() for r in scoped(run) for t in tags_of(docs.read(r["dir"]))}


def say_disagreements(checked: Json) -> None:
    unproven = [t for t, s in checked.items() if weak(s) and s["confirmed"]]
    missing = [t for t, s in checked.items() if not weak(s) and not s["confirmed"]]
    say(f"\nConfirmed although eRank has under 20 or nothing ({len(unproven)}):", unproven)
    say(f"\nNot confirmed although eRank has 20 or more ({len(missing)}):", missing)


def wording_key(term: str) -> str:
    plain = [re.sub(r"s$", "", w) for w in term.lower().replace("-", " ").split()]
    return " ".join(sorted(plain))


def wording_fixes(stored: Json) -> dict[str, str]:
    """Unconfirmed terms whose words Etsy does suggest, in another order or number."""
    offered: dict[str, str] = {}
    for term, entry in stored.items():
        for phrase in [*entry["list"], *([term] if entry["hit"] else [])]:
            offered.setdefault(wording_key(phrase), phrase.lower())
    fixes = {t: offered.get(wording_key(t)) for t, e in stored.items() if not e["hit"]}
    return {t: fix for t, fix in fixes.items() if fix and fix != t}


def cmd_signals(args: argparse.Namespace) -> None:
    """Compare autocomplete with eRank and the tiers across every scoped tag."""
    words, rivals = stores()
    scores = {t: info(t, words, rivals) for t in sorted(scoped_tags(run_dir(args.run)))}
    checked = {t: s for t, s in scores.items() if s["confirmed"] is not None}
    say(f"{len(checked)} of {len(scores)} distinct tags checked")
    share_table("By eRank searches", grouped(checked, lambda s: searches_band(s["s"])))
    share_table("By tier", grouped(checked, lambda s: s["tier"]))
    say_disagreements(checked)
    say("\nWording fixes:", wording_fixes(suggestions()))


def final_tags(old: list[str], swaps: list[list[Any]]) -> list[str]:
    tags = list(old)
    for swap in swaps:
        tags[tags.index(swap[0])] = swap[1]
    return tags


def tag_set_problems(name: str, tags: list[str]) -> list[Any]:
    low = [t.lower() for t in tags]
    if len(low) == TAG_COUNT and len(set(low)) == TAG_COUNT:
        return []
    repeats = [t for t, n in collections.Counter(low).items() if n > 1]
    return [(name, "needs 13 distinct tags", repeats)]


def swap_problems(name: str, new: str, words: Json, rivals: Json) -> list[Any]:
    checks = (
        (len(new) > TAG_LIMIT, "tag over 20 characters"),
        (new.lower() not in words, "no eRank data"),
        (new.lower() not in rivals, "no competition data"),
    )
    return [(name, label, new) for failed, label in checks if failed]


def entry_problems(entry: Json, old: list[str], words: Json, rivals: Json) -> list[Any]:
    name, swaps = entry["short"], entry["swaps"]
    missing = [s[0] for s in swaps if s[0] not in old]
    if missing:
        return [(name, "old tag not on listing", missing)]
    problems = tag_set_problems(name, final_tags(old, swaps))
    for swap in swaps:
        problems += swap_problems(name, swap[1], words, rivals)
    title = entry.get("title") or ""
    if len(title) > TITLE_LIMIT:
        problems.append((name, "title length", len(title)))
    return problems


def plan_problems(run: Path) -> list[Any]:
    _, docs = workspace()
    words, rivals = stores()
    by_id = {str(r["id"]): r for r in scoped(run)} | {r["dir"]: r for r in scoped(run)}
    problems: list[Any] = []
    for key, entry in load(run / "plan.json", {}).items():
        row = by_id.get(key)
        if row is None:
            problems.append((key, "not in scope"))
            continue
        if "tags" in entry:
            problems += new_listing_problems(row["dir"], entry, words, rivals)
            continue
        old = tags_of(docs.read(row["dir"]))
        found = entry_problems(entry, old, words, rivals)
        problems += found
        if not found:
            after = reach(final_tags(old, entry["swaps"]), words, rivals)
            before = reach(old, words, rivals)
            say(f"{entry['short']:32} {row['state']:5} reach {before} -> {after}")
    return problems


def set_tag_problems(name: str, tag: str, own: set[str], words: Json, rivals: Json) -> list[Any]:
    """The design's own phrase may lack data; every other tag needs it."""
    if tag.lower() not in own:
        return swap_problems(name, tag, words, rivals)
    return [(name, "tag over 20 characters", tag)] if len(tag) > TAG_LIMIT else []


def new_listing_problems(name: str, entry: Json, words: Json, rivals: Json) -> list[Any]:
    """A new listing's full set: 13 distinct tags with data, apart from its own phrases."""
    tags, own = entry["tags"], {t.lower() for t in entry.get("own", [])}
    problems = tag_set_problems(name, tags)
    for tag in tags:
        problems += set_tag_problems(name, tag, own, words, rivals)
    title = entry.get("title") or ""
    if not title or len(title) > TITLE_LIMIT:
        problems.append((name, "title missing or over 140", len(title)))
    if not problems:
        say(f"{name[:44]:44} New   reach {reach(tags, words, rivals)}")
    return problems


def cmd_draft(args: argparse.Namespace) -> None:
    """Write new listings' title, tags and lead from plan.json and leads.json.

    A dry run without --write.
    """
    run = run_dir(args.run)
    plan, leads = load(run / "plan.json", {}), load(run / "leads.json", {})
    words, rivals = stores()
    changes = [
        {"dir": key, "title": entry["title"], "tags": entry["tags"]}
        for key, entry in plan.items()
        if "tags" in entry
    ]
    problems: list[Any] = []
    for change in changes:
        name = change["dir"]
        problems += new_listing_problems(name, plan[name], words, rivals)
        if name not in leads:
            problems.append((name, "no lead in leads.json"))
        problems += lead_problems(name, change["title"], leads.get(name))
    say("problems", problems)
    if problems:
        sys.exit(1)
    if args.write:
        write_changes(run, changes, leads)


def cmd_check(args: argparse.Namespace) -> None:
    """Validate plan.json against the live listing files and both stores."""
    problems = plan_problems(run_dir(args.run))
    say("problems", problems)
    if problems:
        sys.exit(1)


def thumbnail(run: Path, listing_id: int, url: str) -> str:
    cache = run / "thumbs" / f"{listing_id}.txt"
    if cache.exists():
        return cache.read_text()
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request) as response:
        picture = Image.open(io.BytesIO(response.read())).convert("RGB")
    width, height = picture.size
    side = min(width, height)
    left, top = (width - side) // 2, (height - side) // 2
    picture = picture.crop((left, top, left + side, top + side)).resize((168, 168))
    buffer = io.BytesIO()
    picture.save(buffer, "JPEG", quality=72)
    data = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(data)
    return data


def listing_card(row: Json, entry: Json, etsy: Json, img: str, scoring: tuple) -> Json:
    words, rivals = scoring
    old = list(etsy["tags"])
    tags = final_tags(old, entry["swaps"])
    removed = {s[0] for s in entry["swaps"]}
    live = row["state"] == "Live"
    draft_note = (
        "Draft, so nobody can find this yet. eRank can't audit a draft, so its numbers "
        "come from the keyword data rather than a listing audit."
    )
    swaps = [
        {
            "id": f"{row['id']}-tag-{slug(s[1])}",
            "old": s[0],
            "new": s[1],
            "note": s[2],
            "flag": s[3],
            "a": info(s[0], words, rivals),
            "b": info(s[1], words, rivals),
        }
        for s in entry["swaps"]
    ]
    return {
        "id": row["id"],
        "short": entry["short"],
        "dir": row["dir"],
        "state": row["state"],
        "url": f"https://www.etsy.com/listing/{row['id']}" if live else None,
        "notice": None if live else draft_note,
        "img": img,
        "oldTitle": html.unescape(etsy["title"]),
        "newTitle": entry.get("title"),
        "why": entry["why"],
        "newLen": len(entry.get("title") or ""),
        "keep": [{"t": t} for t in old if t not in removed],
        "reach0": reach(old, words, rivals),
        "reach1": reach(tags, words, rivals),
        "after": dict(collections.Counter(info(t, words, rivals)["tier"] for t in tags)),
        "swaps": swaps,
    }


def best_niches(cards: list[Json], use: collections.Counter[str]) -> list[Json]:
    board, shown = [], set()
    for card in cards:
        for swap in card["swaps"]:
            score = swap["b"]
            if swap["new"] in shown or score["tier"] not in GOOD_TIERS:
                continue
            shown.add(swap["new"])
            board.append(
                {
                    "t": swap["new"],
                    "est": score["est"],
                    "tees": score["tees"],
                    "share": score["share"],
                    "peak": score["peak"],
                    "n": use[swap["new"].lower()],
                }
            )
    return sorted(board, key=lambda r: -r["est"] / max(r["tees"], 1))


def headline_stats(pairs: list[tuple[list[str], list[str]]], scoring: tuple, rows: list) -> list:
    words, rivals = scoring

    def scores(index: int) -> list[Json]:
        return [info(t, words, rivals) for pair in pairs for t in pair[index]]

    def passing(index: int) -> int:
        return sum(s["tier"] in ("sweet", "small") for s in scores(index))

    weak_before, weak_after = sum(map(weak, scores(0))), sum(map(weak, scores(1)))
    reach_before = sum(reach(p[0], words, rivals) for p in pairs)
    reach_after = sum(reach(p[1], words, rivals) for p in pairs)
    drafts = sum(r["state"] == "Draft" for r in rows)
    return [
        [
            f"{weak_before} of {len(scores(0))}",
            "tags have under 20 measured searches a month or no data at all. "
            f"That falls to {weak_after} if you approve everything.",
        ],
        [
            f"{passing(0)} to {passing(1)}",
            "tag slots that pass your niche test (sweet spot or small niche).",
        ],
        [
            f"{reach_before:,} to {reach_after:,}",
            "shirt searches a month across these listings' sweet-spot, small and busy tags. "
            "Audiences overlap, so this is reach and not traffic.",
        ],
        [f"{drafts} of {len(rows)}", "listings are still drafts, so no search can reach them."],
    ]


def build_cards(run: Path, plan: Json, scoring: tuple) -> tuple[list[Json], list[tuple]]:
    plan = {key: entry for key, entry in plan.items() if "swaps" in entry}
    _, docs = workspace()
    rows = [r for r in scoped(run) if str(r["id"]) in plan]
    ids = ",".join(str(r["id"]) for r in rows)
    params = [("listing_ids", ids), ("includes", "Images")]
    body = transport().get(BATCH_PATH, params=params).json()
    images = {x["listing_id"]: x["images"][0]["url_570xN"] for x in body["results"] if x["images"]}
    cards, pairs = [], []
    for row in rows:
        entry = plan[str(row["id"])]
        etsy = docs.read(row["dir"])["etsy"]
        url = images.get(row["id"])
        img = thumbnail(run, row["id"], url) if url else ""
        cards.append(listing_card(row, entry, etsy, img, scoring))
        pairs.append((list(etsy["tags"]), final_tags(list(etsy["tags"]), entry["swaps"])))
    return cards, pairs


def fill_template(run_name: str, page_copy: Json, data: Json) -> str:
    page = (HERE / "report_template.html").read_text(encoding="utf8")
    for key in ("title", "heading", "meta", "lede", "findings", "notes", "other"):
        page = page.replace(f"__{key.upper()}__", page_copy[key])
    raw = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return page.replace("__KEY__", "nis-seo-" + slug(run_name)).replace("__DATA__", raw)


def cmd_report(args: argparse.Namespace) -> None:
    """Build report.html from plan.json and copy.json."""
    run = run_dir(args.run)
    problems = plan_problems(run)
    if problems:
        sys.exit(f"fix plan.json first: {problems}")
    page_copy = load(run / "copy.json", None)
    if page_copy is None:
        sys.exit("write copy.json first")
    scoring = stores()
    cards, pairs = build_cards(run, load(run / "plan.json", {}), scoring)
    use = collections.Counter(t.lower() for pair in pairs for t in pair[1])
    stats = headline_stats(pairs, scoring, scoped(run))
    data = {"listings": cards, "tot": {"stats": stats}, "board": best_niches(cards, use)}
    (run / "report.html").write_text(fill_template(args.run, page_copy, data), encoding="utf8")
    titles = sum(1 for c in cards if c["newTitle"])
    swaps = sum(len(c["swaps"]) for c in cards)
    say(f"{run / 'report.html'}: {swaps} tag swaps, {titles} titles")


def read_decisions(folder: str) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for path in Path(folder).glob("*.json"):
        body = load(path, {})
        out[path.stem] = body.get("decision") or body.get("data", {}).get("decision")
    return out


def resolve_tags(row: Json, entry: Json, tags: list[str], decisions: dict) -> list[str]:
    rejected, undecided = [], []
    for swap in entry["swaps"]:
        verdict = decisions.get(f"{row['id']}-tag-{slug(swap[1])}")
        if verdict == "approve":
            tags[tags.index(swap[0])] = swap[1]
        else:
            (rejected if verdict == "reject" else undecided).append(f"{swap[0]} (not {swap[1]})")
    if rejected:
        say("   rejected, these stay:", rejected)
    if undecided:
        say("   UNDECIDED, these stay:", undecided)
    return tags


def resolve_title(row: Json, entry: Json, decisions: dict) -> str | None:
    if not entry.get("title"):
        say(f"{entry['short']}: title none suggested")
        return None
    verdict = decisions.get(f"{row['id']}-title")
    say(f"{entry['short']}: title {verdict or 'UNDECIDED'}")
    return entry["title"] if verdict == "approve" else None


def decision_keys(row: Json, entry: Json) -> set[str]:
    keys = {f"{row['id']}-tag-{slug(s[1])}" for s in entry["swaps"]}
    return keys | ({f"{row['id']}-title"} if entry.get("title") else set())


def resolve_listing(row: Json, entry: Json, etsy: Json, decisions: dict) -> Json:
    title = resolve_title(row, entry, decisions)
    return {
        "dir": row["dir"],
        "short": entry["short"],
        "title": title,
        "tags": resolve_tags(row, entry, list(etsy["tags"]), decisions),
        "terms": title_terms(title or etsy["title"]),
        "lead": etsy["description"]["lead"],
    }


def cmd_resolve(args: argparse.Namespace) -> None:
    """Turn saved report decisions into changes.json. Unapproved items stay as they are."""
    run = run_dir(args.run)
    _, docs = workspace()
    decisions = read_decisions(args.decisions)
    say(dict(collections.Counter(decisions.values())))
    plan = load(run / "plan.json", {})
    rows = [r for r in scoped(run) if str(r["id"]) in plan]
    known: set[str] = set()
    changes = []
    for row in rows:
        entry = plan[str(row["id"])]
        changes.append(resolve_listing(row, entry, docs.read(row["dir"])["etsy"], decisions))
        known |= decision_keys(row, entry)
    say("unknown decisions", sorted(set(decisions) - known))
    save(run / "changes.json", changes)


def lead_problems(name: str, title: str, lead: str | None) -> list[Any]:
    if lead is None:
        return []
    opening = lead.lower()[:LEAD_WINDOW]
    missing = [t for t in title_terms(title) if t.lower() not in opening]
    return [(name, "term missing from lead opening", t) for t in missing]


def change_problems(change: Json, etsy: Json, lead: str | None) -> list[Any]:
    name = change["dir"]
    title = html.unescape(change["title"] or etsy["title"])
    problems = tag_set_problems(name, change["tags"])
    problems += [(name, "tag over 20", t) for t in change["tags"] if len(t) > TAG_LIMIT]
    if len(title) > TITLE_LIMIT:
        problems.append((name, "title length", len(title)))
    return problems + lead_problems(name, title, lead)


def apply_change(doc: Json, change: Json, lead: str | None) -> Json:
    doc["etsy"]["tags"] = list(change["tags"])
    if change["title"]:
        doc["etsy"]["title"] = change["title"]
    if lead is not None:
        doc["etsy"]["description"]["lead"] = lead
    return doc


def write_changes(run: Path, changes: list[Json], leads: Json) -> None:
    ws, docs = workspace()
    backup = run / "yaml-backup"
    backup.mkdir(exist_ok=True)
    for change in changes:
        name = change["dir"]
        shutil.copy2(ws.listing_file(name), backup / f"{name}.yaml")
        expected = apply_change(copy.deepcopy(docs.read(name)), change, leads.get(name))
        docs.edit(name, lambda doc, c=change, n=name: apply_change(doc, c, leads.get(n)))
        if docs.read(name) != expected:
            sys.exit(f"{name}: file differs from the intended edit")
        ws.load_listing(name)
    say(f"written and verified {len(changes)}. Backups in {backup}")


def cmd_write(args: argparse.Namespace) -> None:
    """Apply changes.json and leads.json to listing.yaml. A dry run without --write."""
    run = run_dir(args.run)
    _, docs = workspace()
    changes = load(run / "changes.json", None)
    if changes is None:
        sys.exit("run `resolve` first")
    leads = load(run / "leads.json", {})
    problems: list[Any] = []
    for change in changes:
        etsy = docs.read(change["dir"])["etsy"]
        lead = leads.get(change["dir"])
        problems += change_problems(change, etsy, lead)
        added = {t.lower() for t in change["tags"]} - {t.lower() for t in etsy["tags"]}
        title = "CHANGE" if change["title"] and change["title"] != etsy["title"] else "keep"
        new_lead = "CHANGE" if lead and lead != etsy["description"]["lead"] else "keep"
        say(f"{change['dir'][:44]:44} title {title}, tags changed {len(added)}, lead {new_lead}")
    say("problems", problems)
    if problems:
        sys.exit(1)
    if args.write:
        write_changes(run, changes, leads)


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = top.add_subparsers(dest="command", required=True)

    def command(name: str, handler: Any) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=(handler.__doc__ or "").splitlines()[0])
        sub.add_argument("run")
        sub.set_defaults(handler=handler)
        return sub

    command("scope", cmd_scope).add_argument("patterns", nargs="+")
    niche = command("niche", cmd_niche)
    niche.add_argument("queries", nargs="+")
    niche.add_argument("--picks", type=int, default=14)
    niche.add_argument("--skip", default="custom|personali[sz]ed|disney")
    command("ingest", cmd_ingest)
    command("competition", cmd_competition).add_argument("file", nargs="?")
    command("suggest", cmd_suggest).add_argument("file", nargs="?")
    command("ingest-suggestions", cmd_ingest_suggestions)
    command("discover", cmd_discover).add_argument("--limit", type=int, default=100)
    command("signals", cmd_signals)
    command("score", cmd_score).add_argument("file", nargs="?")
    command("check", cmd_check)
    command("report", cmd_report)
    command("resolve", cmd_resolve).add_argument("decisions")
    command("write", cmd_write).add_argument("--write", action="store_true")
    command("draft", cmd_draft).add_argument("--write", action="store_true")
    return top


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
