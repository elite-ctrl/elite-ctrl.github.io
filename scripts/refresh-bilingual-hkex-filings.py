#!/usr/bin/env python3
"""Refresh the bilingual HKEXnews filings cache (studio computer).

The Live page reads cache-meta.json, stocks.json, and tiers.json on arrival.
After a code or name is chosen, it fetches one issuer file at
filings/{prefix}/{code}.json.gz (prefix is the first two digits of the
five-digit stock code). This script writes that split layout inside the
work directory only. It does not write those Live files, does not download
PDF bodies, does not write filings-cache.json or filings-cache.json.gz, and
does not add a GitHub Actions cron. The Wednesday and Sunday run, around
08:30 Asia/Hong_Kong, is the Grok Bot routine on the studio computer.

Window: the last three calendar years through today in Asia/Hong_Kong.
29 February falls back to 28 February. The on-disk language key C means
Traditional Chinese. The title-search servlet is called with lang=zh for
that key, and lang=E for English. Sending the disk key as the servlet
language returns English, so this script never does that.

Incremental runs may reuse monthly raw files outside the lookback. They
always re-pull the last 14 calendar days in Asia/Hong_Kong, including
today (start = today minus 13 days), even when those days sit inside a
monthly file already marked complete. That keeps mid-window headline
revisions from going stale. About once a month, re-pull the whole
three-year window with pull --full-repull. Do not schedule that pull
from GitHub Actions.

Build strips, with a contains match (not an exact match, and not
startswith): Monthly Returns (the whole Tier 1, including 月報表 and
51500); Next Day Disclosure share buybacks (other NDRs stay, including
the standard form title "changes in issued share capital and/or share
buybacks" / 已發行股本及/或股份購回; AGM repurchase circulars stay);
warrants, options, and 牛熊證 (CBBCs); Debt and Structured Products
(債券及結構性產品), code 70000, including cancelled or reissued prefixes,
and documents-on-display types 57000, 58000, and 59000. Those debt chips
are removed from tiers.json as well as from filing rows. An issuer with
no paired filings left is omitted from the hasCache universe and gets
no issuer file.

Commands (work directory defaults to data/hkex-filings-work/, which is
gitignored; override with --work or HKEX_FILINGS_ROOT):

  python3 scripts/refresh-bilingual-hkex-filings.py --self-test
  python3 scripts/refresh-bilingual-hkex-filings.py pull --work DIR
  python3 scripts/refresh-bilingual-hkex-filings.py build --work DIR
  python3 scripts/refresh-bilingual-hkex-filings.py check --work DIR
  python3 scripts/refresh-bilingual-hkex-filings.py all --work DIR
  python3 scripts/refresh-bilingual-hkex-filings.py pull --full-repull --work DIR
  python3 scripts/refresh-bilingual-hkex-filings.py gzip --work DIR

build writes cache-meta.json, stocks.json, tiers.json, and, when the
build is shippable, filings/{prefix}/{code}.json.gz (gzip-9) in the work
directory. A later shippable run rewrites an issuer file only when its
compact JSON changed, leaves unchanged gzip files in place, and deletes
orphan issuer files. A failed or partial build leaves the existing issuer
gzip files untouched. gzip is the ship-prep confirmation: it runs only
after the quality gate would pass, deletes any leftover monolith, and
does not write filings-cache.json.gz. Copying the split onto the site is
a later pull request. See scripts/bilingual-hkex-filings.md.

cookies.txt, if the studio keeps one, is read from the work directory
and is never written by this script. Do not commit it.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import sys
import time
import traceback
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK = REPO_ROOT / "data" / "hkex-filings-work"
HK_TZ = ZoneInfo("Asia/Hong_Kong")

# Live site outputs. A refresh must not write these. A later ship PR copies
# reviewed artefacts out of the work directory.
LIVE_OUTPUTS = (
    REPO_ROOT / "cache-meta.json",
    REPO_ROOT / "filings-cache.json",
    REPO_ROOT / "filings-cache.json.gz",
    REPO_ROOT / "filings-cache.partial.json",
    REPO_ROOT / "stocks.json",
    REPO_ROOT / "tiers.json",
    REPO_ROOT / "REFRESH_REPORT.txt",
    REPO_ROOT / "refresh_progress.json",
)
LIVE_FILINGS = REPO_ROOT / "filings"

# Names that used to be the whole-market monolith. A successful split build
# removes them from the work directory and never writes them again.
MONOLITH_NAMES = (
    "filings-cache.json",
    "filings-cache.json.gz",
    "filings-cache.partial.json",
)

META_KEYS = (
    "prototypeStamp",
    "stamp",
    "snapshot",
    "source",
    "pairing",
    "note",
    "exclusions",
    "issuerCount",
    "pairCount",
    "sourceWindow",
)

ISSUER_PACK_KEYS = (
    "code",
    "stockId",
    "nameEn",
    "nameTc",
    "snapshot",
    "sourceWindow",
    "stats",
    "filings",
)

FILING_ROW_KEYS = (
    "dateTime",
    "newsIdEn",
    "newsIdTc",
    "titleEn",
    "titleTc",
    "tier1Code",
    "tier1En",
    "tier1Tc",
    "tier2En",
    "tier2Tc",
    "categoryEn",
    "categoryTc",
    "pdfEn",
    "pdfTc",
    "fileInfoEn",
    "fileInfoTc",
)

ISSUER_GZIP_SUFFIX = ".json.gz"

PDF_BASE = "https://www1.hkexnews.hk"
API = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
REF = "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Disk key C is Traditional Chinese. The servlet language is zh.
# Do not put the disk key in the lang parameter.
API_LANG = {"E": "E", "C": "zh"}
REF_LANG = {"E": "en", "C": "zh"}
DISK_LANGS = ("E", "C")

LOOKBACK_DAYS = 14
MAX_ROWS = 10000  # HKEXnews caps loadedRecord at 10000
SLEEP_SEC = 8.5
MAX_RETRIES = 6
STAMP = "Beta"

# Live issuer-split snapshot, 11 November 2026 (3,072 issuers / 273,418 pairs).
# The 10 November band (3,072 / 273,587) was the pre-split monolith.
# check refuses a build whose counts sit outside ±20% of these figures.
# Revise the baseline when a reviewed ship replaces the Live cache.
SNAPSHOT_AS_OF = "11 November 2026"
SNAPSHOT_ISSUERS = 3072
SNAPSHOT_PAIRS = 273418
SNAPSHOT_TOLERANCE = 0.20

DEBT_TIER_CODES = frozenset({"70000", "57000", "58000", "59000"})
DEBT_NAME_MARKERS = (
    "Debt and Structured Products",
    "債券及結構性產品",
    "Documents on Display (Debt Issuance Programmes)",
    "Documents on Display (Debt Securities)",
    "Documents on Display (Structured Products)",
    "展示文件（債務證券發行計劃）",
    "展示文件（債務證券）",
    "展示文件（結構性產品）",
)

STUB_RE = re.compile(r"published in Chinese", re.I)
DERIV_NAME_RE = re.compile(
    r"WARRANT|\bOPTION\b|\bOPTIONS\b|\bCBBC\b|\bCBBCs\b|牛熊|窩輪|認股證|認股權|"
    r"認沽|認購|期權|權證|"
    r"@EC\d|@EP\d|@RP\d|@SE\d|"
    r"#\w+\s+RC\d|"
    r"\bDW\b|\bELI\b|INLINE WARRANT",
    re.I,
)
DERIV_STOCK_NAME_RE = re.compile(
    r"WARRANT|\bOPTION\b|\bOPTIONS\b|\bCBBC\b|牛熊|窩輪|認股證|認沽|認購|期權|權證|"
    r"@EC\d|@EP\d|@RP\d|#\w+\s+RC\d",
    re.I,
)

REFERENCE_URLS = {
    "activestock_sehk_e.json": "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_e.json",
    "activestock_sehk_c.json": "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_c.json",
    "tierone_e.json": "https://www1.hkexnews.hk/ncms/script/eds/tierone_e.json",
    "tierone_c.json": "https://www1.hkexnews.hk/ncms/script/eds/tierone_c.json",
    "tiertwo_e.json": "https://www1.hkexnews.hk/ncms/script/eds/tiertwo_e.json",
    "tiertwo_c.json": "https://www1.hkexnews.hk/ncms/script/eds/tiertwo_c.json",
}

_NETWORK_OK = False


class RefreshError(RuntimeError):
    """A refresh step failed closed. Nothing Live was written."""


@dataclass
class WorkPaths:
    root: Path
    data: Path
    raw: Path
    log: Path
    cookie: Path
    meta: Path
    stocks: Path
    tiers: Path
    filings: Path
    progress: Path
    report: Path
    pull_status: Path
    build_manifest: Path


PATHS: WorkPaths | None = None


@dataclass(frozen=True)
class FetchJob:
    """A title-search window. force=True ignores a complete raw file."""

    lang: str
    start: date
    end: date
    force: bool
    reused_complete: bool


@dataclass(frozen=True)
class CacheJob:
    """Read a complete month file and keep rows dated before keep_before."""

    lang: str
    start: date
    end: date
    keep_before: date


Job = FetchJob | CacheJob


@dataclass
class IngestStats:
    raw_en: int = 0
    raw_tc: int = 0
    skipped_non_equity: int = 0
    skipped_derivative_rows: int = 0


def configure(work: Path | None) -> WorkPaths:
    """Point every output at the work directory, never at the Live site files."""
    global PATHS
    if work is None:
        env = os.environ.get("HKEX_FILINGS_ROOT")
        work = Path(env) if env else DEFAULT_WORK
    root = work.expanduser().resolve()
    live_filings = LIVE_FILINGS.resolve()
    if root == REPO_ROOT or root == live_filings or live_filings in root.parents:
        raise RefreshError(
            "Refusing to use the repository root or the Live filings tree as the work directory. "
            "That would overwrite Live cache-meta.json, stocks.json, tiers.json, or issuer files."
        )
    paths = WorkPaths(
        root=root,
        data=root / "data",
        raw=root / "data" / "_local" / "raw_pulls",
        log=root / "data" / "_local" / "logs" / "refresh.log",
        cookie=root / "data" / "_local" / "cookies.txt",
        meta=root / "cache-meta.json",
        stocks=root / "stocks.json",
        tiers=root / "tiers.json",
        filings=root / "filings",
        progress=root / "refresh_progress.json",
        report=root / "REFRESH_REPORT.txt",
        pull_status=root / "pull-status.json",
        build_manifest=root / "build-manifest.json",
    )
    for path in (
        paths.meta,
        paths.stocks,
        paths.tiers,
        paths.filings,
        paths.progress,
        paths.report,
        paths.pull_status,
        paths.build_manifest,
    ):
        refuse_live_write(path)
    for name in MONOLITH_NAMES:
        refuse_live_write(root / name)
    PATHS = paths
    return paths


def refuse_live_write(path: Path) -> None:
    resolved = path.expanduser().resolve()
    live = {item.resolve() for item in LIVE_OUTPUTS}
    live_filings = LIVE_FILINGS.resolve()
    under_live_filings = resolved == live_filings or live_filings in resolved.parents
    if resolved in live or resolved == REPO_ROOT or under_live_filings:
        raise RefreshError(
            f"Refusing to write Live site file {resolved}. "
            "Build into the work directory. Ship artefacts in a separate pull request."
        )


def require_paths() -> WorkPaths:
    if PATHS is None:
        raise RefreshError("Work directory is not configured.")
    return PATHS


def log(msg: str) -> None:
    ts = datetime.now(HK_TZ).strftime("%Y-%m-%d %H:%M:%S HKT")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    paths = PATHS
    if paths is None:
        return
    paths.log.parent.mkdir(parents=True, exist_ok=True)
    with paths.log.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def atomic_write(path: Path, text: str) -> None:
    refuse_live_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    refuse_live_write(tmp)
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def allow_network(enabled: bool) -> None:
    global _NETWORK_OK
    _NETWORK_OK = enabled


def today_hkt(now: datetime | None = None) -> date:
    """Calendar date in Asia/Hong_Kong. A naive datetime is read as HKT."""
    if now is None:
        now = datetime.now(HK_TZ)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=HK_TZ)
    else:
        now = now.astimezone(HK_TZ)
    return now.date()


def rolling_from_date(today: date) -> date:
    """First day of the three-year window. 29 February falls back to 28 February."""
    try:
        return date(today.year - 3, today.month, today.day)
    except ValueError:
        return date(today.year - 3, today.month, 28)


def lookback_start(today: date, days: int = LOOKBACK_DAYS) -> date:
    """First day of the inclusive lookback. 14 days ending today starts 13 days earlier.

    10 November 2026 → 28 October 2026 through 10 November 2026 (14 dates).
    """
    if days < 1:
        raise RefreshError("lookback days must be at least 1")
    return today - timedelta(days=days - 1)


def inclusive_dates(start: date, end: date) -> set[date]:
    days: set[date] = set()
    cursor = start
    while cursor <= end:
        days.add(cursor)
        cursor += timedelta(days=1)
    return days


def ymd(day: date) -> str:
    return day.strftime("%Y%m%d")


def snapshot_label(today: date) -> str:
    return f"{today.day} {today.strftime('%B %Y')} (Asia/Hong_Kong)"


def month_windows(start: date, end: date) -> list[tuple[date, date]]:
    out = []
    year, month = start.year, start.month
    while True:
        first = date(year, month, 1)
        last = date(year, month, monthrange(year, month)[1])
        if first > end:
            break
        window_start = max(first, start)
        window_end = min(last, end)
        out.append((window_start, window_end))
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return out


def split_window(start: date, end: date) -> list[tuple[date, date]]:
    if start >= end:
        return [(start, end)]
    days = (end - start).days
    mid = start.toordinal() + days // 2
    left_end = date.fromordinal(mid)
    right_start = date.fromordinal(mid + 1)
    if right_start > end:
        return [(start, end)]
    return [(start, left_end), (right_start, end)]


def plan_window(
    lang: str,
    start: date,
    end: date,
    lookback_from: date,
    *,
    complete: bool,
    full_repull: bool,
) -> list[Job]:
    """Plan one monthly window.

    A complete file that ends before the lookback is reused. A complete file
    that overlaps the lookback is reused only for rows before the lookback;
    the lookback slice is a forced pull. A file that is not complete is
    fetched whole, so its lookback days are fresh without a second request.
    """
    if full_repull:
        return [FetchJob(lang, start, end, True, False)]
    if end < lookback_from or not complete:
        reused = bool(complete and end < lookback_from)
        return [FetchJob(lang, start, end, False, reused)]
    fresh_start = max(start, lookback_from)
    jobs: list[Job] = []
    if start < fresh_start:
        jobs.append(CacheJob(lang, start, end, fresh_start))
    jobs.append(FetchJob(lang, fresh_start, end, True, False))
    return jobs


def plan_market(
    today: date,
    from_date: date,
    is_complete: Callable[[str, date, date], bool],
    *,
    full_repull: bool = False,
) -> list[Job]:
    lookback_from = lookback_start(today)
    jobs: list[Job] = []
    for start, end in month_windows(from_date, today):
        for lang in DISK_LANGS:
            complete = False if full_repull else is_complete(lang, start, end)
            jobs.extend(
                plan_window(
                    lang,
                    start,
                    end,
                    lookback_from,
                    complete=complete,
                    full_repull=full_repull,
                )
            )
    return jobs


def fresh_dates(jobs: Iterable[Job], lang: str, lookback_from: date, today: date) -> set[date]:
    """Dates in the lookback that this plan fetches rather than reuses."""
    found: set[date] = set()
    for job in jobs:
        if not isinstance(job, FetchJob) or job.lang != lang or job.reused_complete:
            continue
        cursor = max(job.start, lookback_from)
        last = min(job.end, today)
        while cursor <= last:
            found.add(cursor)
            cursor += timedelta(days=1)
    return found


def uncovered_lookback(jobs: Iterable[Job], lookback_from: date, today: date) -> dict[str, list[date]]:
    expected = inclusive_dates(lookback_from, today)
    missing: dict[str, list[date]] = {}
    job_list = list(jobs)
    for lang in DISK_LANGS:
        gap = sorted(expected - fresh_dates(job_list, lang, lookback_from, today))
        if gap:
            missing[lang] = gap
    return missing


def assert_lookback_planned(jobs: Iterable[Job], today: date) -> None:
    missing = uncovered_lookback(jobs, lookback_start(today), today)
    if not missing:
        return
    bits = []
    for lang, days in missing.items():
        shown = ", ".join(day.isoformat() for day in days[:5])
        bits.append(f"{lang} missing {len(days)} day(s) ({shown})")
    raise RefreshError(
        "Lookback plan does not re-pull the last 14 days in Asia/Hong_Kong: " + "; ".join(bits)
    )


def job_to_dict(job: Job) -> dict[str, Any]:
    if isinstance(job, CacheJob):
        return {
            "kind": "cache",
            "lang": job.lang,
            "start": job.start.isoformat(),
            "end": job.end.isoformat(),
            "keepBefore": job.keep_before.isoformat(),
        }
    return {
        "kind": "fetch",
        "lang": job.lang,
        "start": job.start.isoformat(),
        "end": job.end.isoformat(),
        "force": job.force,
        "reusedComplete": job.reused_complete,
    }


def job_from_dict(raw: dict[str, Any]) -> Job:
    try:
        kind = raw["kind"]
        lang = raw["lang"]
        start = date.fromisoformat(raw["start"])
        end = date.fromisoformat(raw["end"])
        if kind == "cache":
            return CacheJob(lang, start, end, date.fromisoformat(raw["keepBefore"]))
        if kind == "fetch":
            return FetchJob(lang, start, end, bool(raw["force"]), bool(raw["reusedComplete"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise RefreshError(f"unreadable pull job: {exc}") from exc
    raise RefreshError(f"unknown pull job kind {kind!r}")


def should_reuse_raw(force: bool, complete: bool) -> bool:
    """A complete raw file is reusable unless this pull is forced.

    Lookback slices and a monthly full re-pull set force, so a file marked
    complete is still fetched again.
    """
    return bool(complete) and not force


def servlet_lang(disk_lang: str) -> str:
    """Map a disk key to the title-search lang parameter. Never returns C."""
    try:
        api_lang = API_LANG[disk_lang]
    except KeyError as exc:
        raise RefreshError(f"Unknown disk language {disk_lang!r}. Use E or C.") from exc
    if api_lang not in {"E", "zh"}:
        raise RefreshError(f"Refusing servlet language {api_lang!r}.")
    return api_lang


def servlet_lang_problems(mapping: dict[str, str] | None = None) -> list[str]:
    mapping = API_LANG if mapping is None else mapping
    problems = []
    if set(mapping) != {"E", "C"}:
        problems.append("disk language keys must be E and C")
    for disk, servlet in mapping.items():
        if servlet not in {"E", "zh"} or servlet == "C":
            problems.append(f"disk key {disk} must not call the servlet with {servlet!r}")
    if "C" in mapping.values():
        problems.append("servlet language C is forbidden; Traditional Chinese is lang=zh")
    return problems


def search_params(lang: str, from_s: str, to_s: str, row_range: int, stock_id: str = "") -> dict[str, str]:
    return {
        "lang": servlet_lang(lang),
        "category": "0",
        "market": "SEHK",
        "searchType": "1",
        "documentType": "-1",
        "t1code": "-2",
        "t2Gcode": "-2",
        "t2code": "-2",
        "stockId": stock_id,
        "fromDate": from_s,
        "toDate": to_s,
        "title": "",
        "rowRange": str(row_range),
        "sortBy": "0",
        "sortDir": "0",
    }


def load_cookie_header() -> str:
    """Read a Netscape cookie jar if the operator left one in the work directory.

    This function never creates cookies.txt and never logs cookie values.
    """
    path = require_paths().cookie
    if not path.exists():
        return ""
    parts = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line or line.startswith("#"):
            continue
        bits = line.split("\t")
        if len(bits) >= 7:
            parts.append(f"{bits[5]}={bits[6]}")
    return "; ".join(parts)


def http_get(url: str, timeout: int = 180, referer: str | None = None) -> tuple[int, bytes]:
    """GET one HKEXnews URL. Self-test and build leave the network disabled."""
    if not _NETWORK_OK:
        raise RuntimeError("HKEXnews fetch blocked: network is disabled for this command")
    import http.client

    headers = {
        "User-Agent": UA,
        "Referer": referer or REF,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    cookie = load_cookie_header()
    if cookie:
        headers["Cookie"] = cookie
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as resp:
            try:
                return resp.getcode(), resp.read()
            except (http.client.IncompleteRead, ConnectionError, TimeoutError, URLError) as exc:
                log(f"http_get read error: {type(exc).__name__}: {exc}")
                return 598, b""
    except HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        return exc.code, body
    except (URLError, TimeoutError, ConnectionError) as exc:
        log(f"http_get connect error: {type(exc).__name__}: {exc}")
        return 599, b""


def parse_api(body: bytes) -> dict:
    text = body.decode("utf-8", errors="replace")
    payload = json.loads(text)
    if isinstance(payload.get("result"), str):
        payload["result"] = json.loads(payload["result"])
    if payload.get("result") is None:
        payload["result"] = []
    return payload


def api_search(lang: str, from_s: str, to_s: str, row_range: int, stock_id: str = "") -> dict:
    params = search_params(lang, from_s, to_s, row_range, stock_id)
    url = API + "?" + urlencode(params)
    referer_lang = REF_LANG.get(lang, "en")
    referer = f"https://www1.hkexnews.hk/search/titlesearch.xhtml?lang={referer_lang}"
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        code, body = http_get(url, referer=referer)
        if code == 200 and body:
            try:
                return parse_api(body)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                last_err = exc
                log(f"parse fail attempt {attempt + 1}: {exc}")
        else:
            last_err = RuntimeError(f"http {code} bytes={len(body)}")
            log(f"HTTP {code} attempt {attempt + 1} for {lang} {from_s}-{to_s} rr={row_range}")
            if code in (403, 429, 598, 599) or code >= 500:
                time.sleep(SLEEP_SEC * (2 ** attempt))
                continue
        time.sleep(SLEEP_SEC * (1.5 ** attempt))
    raise RuntimeError(f"API failed after retries: {last_err}")


def raw_path(lang: str, start: date, end: date) -> Path:
    return require_paths().raw / f"{lang}_{ymd(start)}_{ymd(end)}.json"


def raw_is_complete(lang: str, start: date, end: date) -> bool:
    path = raw_path(lang, start, end)
    meta_path = path.with_suffix(".meta.json")
    if not path.exists() or not meta_path.exists():
        return False
    try:
        return bool(json.loads(meta_path.read_text(encoding="utf-8")).get("complete"))
    except (OSError, json.JSONDecodeError, TypeError):
        return False


def read_raw_json(lang: str, start: date, end: date) -> list[dict]:
    path = raw_path(lang, start, end)
    if not raw_is_complete(lang, start, end):
        raise RefreshError(f"raw pull incomplete {lang} {start.isoformat()} {end.isoformat()}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RefreshError(f"raw pull is not a list: {path.name}")
    return payload


def fetch_window(lang: str, start: date, end: date, depth: int = 0, force: bool = False) -> list[dict]:
    """Fetch all rows for [start, end], splitting when HKEXnews caps the window."""
    del depth  # retained so logs and traces still show the original recursion shape
    paths = require_paths()
    paths.raw.mkdir(parents=True, exist_ok=True)
    path = raw_path(lang, start, end)
    meta_path = path.with_suffix(".meta.json")
    if should_reuse_raw(force, raw_is_complete(lang, start, end)):
        rows = json.loads(path.read_text(encoding="utf-8"))
        log(f"SKIP cached {lang} {ymd(start)}-{ymd(end)} n={len(rows)}")
        return rows

    log(f"PROBE {lang} {ymd(start)}-{ymd(end)} force={force}")
    time.sleep(SLEEP_SEC)
    probe = api_search(lang, ymd(start), ymd(end), 100)
    count = int(probe.get("recordCnt") or 0)
    log(f"  recordCnt={count}")
    if count == 0:
        _write_raw(path, meta_path, [], {"complete": True, "recordCnt": 0, "force": force})
        return []

    if count > MAX_ROWS and start != end:
        return _fetch_split(lang, start, end, path, meta_path, count, force)

    time.sleep(SLEEP_SEC)
    log(f"FETCH {lang} {ymd(start)}-{ymd(end)} rowRange={count}")
    full = api_search(lang, ymd(start), ymd(end), count)
    rows = full.get("result") or []
    loaded = int(full.get("loadedRecord") or len(rows))
    has_next = bool(full.get("hasNextRow"))
    if (has_next or loaded < count or len(rows) < count) and start != end:
        log(f"  incomplete loaded={loaded} cnt={count} got={len(rows)} hasNext={has_next}; splitting")
        return _fetch_split(lang, start, end, path, meta_path, count, force)
    if has_next or loaded < count or len(rows) < count:
        log(f"  WARN cannot split further; keeping {len(rows)}")

    _write_raw(
        path,
        meta_path,
        rows,
        {"complete": True, "recordCnt": count, "got": len(rows), "force": force},
    )
    log(f"  saved {len(rows)} -> {path.name}")
    return rows


def _fetch_split(
    lang: str,
    start: date,
    end: date,
    path: Path,
    meta_path: Path,
    count: int,
    force: bool,
) -> list[dict]:
    parts: list[dict] = []
    for left, right in split_window(start, end):
        parts.extend(fetch_window(lang, left, right, force=force))
    unique = _dedupe_news(parts)
    _write_raw(
        path,
        meta_path,
        unique,
        {"complete": True, "recordCnt": count, "got": len(unique), "split": True, "force": force},
    )
    return unique


def _write_raw(path: Path, meta_path: Path, rows: list[dict], meta: dict) -> None:
    refuse_live_write(path)
    refuse_live_write(meta_path)
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def _dedupe_news(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique = []
    for row in rows:
        news_id = str(row.get("NEWS_ID") or "")
        if news_id and news_id in seen:
            continue
        if news_id:
            seen.add(news_id)
        unique.append(row)
    return unique


def is_derivative_issuer(code: str, name_en: str = "", name_tc: str = "") -> bool:
    """True for warrant, option, and CBBC wrappers, not ordinary equity or ETFs."""
    if not code or not str(code).isdigit():
        return True
    number = int(code)
    # Main and GEM equities and ETFs use 00001–09999. Codes at or above 10000
    # are derivative warrants, options, callable bull/bear contracts, or
    # debt and structured-product counters. RMB counters in 8xxxx stay out
    # of the issuer universe; their filings attach to the primary 0xxxx code.
    if number >= 10000:
        return True
    if DERIV_NAME_RE.search(f"{name_en} {name_tc}"):
        return True
    return False


def is_derivative_filing_row(row: dict) -> bool:
    stock_name = row.get("STOCK_NAME") or ""
    flat = re.sub(r"<br\s*/?>", " ", stock_name, flags=re.I)
    if DERIV_STOCK_NAME_RE.search(flat):
        return True
    code = primary_code(row.get("STOCK_CODE") or "")
    if code and is_derivative_issuer(code):
        return True
    return False


def primary_code(stock_code: str) -> str:
    if not stock_code:
        return ""
    part = re.split(r"<br\s*/?>|/", stock_code, maxsplit=1, flags=re.I)[0].strip()
    digits = re.sub(r"\D", "", part)
    if not digits:
        return ""
    return digits.zfill(5)[-5:]


def clean_text(value: str) -> str:
    """Decode HKEXnews HTML entities. Unescape twice for a double-encoded slash."""
    if not value:
        return ""
    text = unescape(str(value))
    if "&" in text:
        text = unescape(text)
    return text


def contains_any(blob: str, markers: tuple[str, ...]) -> bool:
    return any(marker in blob for marker in markers)


def parse_category(long_text: str) -> tuple[str, str]:
    if not long_text:
        return "", ""
    text = long_text.strip()
    match = re.match(r"^(.*?)\s*-\s*\[(.*)\]\s*$", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return text, ""


def classify_row(row: dict, t1_name_to_code: dict, t2_by_t1: dict) -> dict:
    long_text = clean_text(row.get("LONG_TEXT") or "").strip()
    tier1_name, tier2_name = parse_category(long_text)
    tier1_code = str(t1_name_to_code.get(tier1_name, "") or "")
    if tier1_code == "51500" or "Monthly Returns" in tier1_name or "月報表" in tier1_name:
        tier1_code = "51500"
    if tier1_code == "50000" or "Next Day Disclosure" in tier1_name or "翌日披露" in tier1_name:
        tier1_code = tier1_code or "50000"
    tier2 = t2_by_t1.get(str(tier1_code), {}).get(tier2_name)
    return {
        "tier1Code": tier1_code or "",
        "tier1Name": tier1_name,
        "tier2Name": tier2_name,
        "tier2Code": (tier2 or {}).get("code", "") if tier2 else "",
        "category": long_text,
    }


def is_debt_or_structured_product(tier1_code: str, tier1_name: str, category: str) -> bool:
    """Whole Tier 1 Debt and Structured Products, including a cancelled or reissued prefix.

    Also the related documents-on-display types 57000, 58000, and 59000.
    A contains match, so a prefix does not hide the chip. Generic announcements
    that merely mention a debt security are not this tier and stay.
    """
    if str(tier1_code or "").strip() in DEBT_TIER_CODES:
        return True
    blob = f"{clean_text(tier1_name)} {clean_text(category)}"
    return contains_any(blob, DEBT_NAME_MARKERS)


def is_excluded(tier1_code: str, tier1_name: str, tier2_name: str, category: str, title: str = "") -> bool:
    """Strip Monthly Returns, NDR share buybacks, and Debt and Structured Products.

    The standard NDR form title ("changes in issued share capital and/or share
    buybacks" / 已發行股本及/或股份購回) is not a buyback on its own. Other NDRs
    stay. AGM repurchase circulars are not NDRs and stay.
    """
    tier1 = clean_text(tier1_name)
    tier2 = clean_text(tier2_name)
    cat = clean_text(category)
    filing_title = clean_text(title)
    if is_debt_or_structured_product(tier1_code, tier1_name, category):
        return True
    if (
        tier1_code == "51500"
        or "Monthly Returns" in tier1
        or "Monthly Returns" in cat
        or "月報表" in tier1
        or "月報表" in cat
    ):
        return True
    is_ndr = (
        tier1_code == "50000"
        or "Next Day Disclosure" in tier1
        or "Next Day Disclosure" in cat
        or "翌日披露" in tier1
        or "翌日披露" in cat
    )
    if not is_ndr:
        return False
    if any(token in tier2 or token in cat for token in ("Share Buyback", "Share Buy-back", "股份購回")):
        return True
    if re.search(r"Share Buy-?backs?", filing_title, re.I) or "股份購回" in filing_title:
        boilerplate = re.search(
            r"changes in issued share(?:s| capital)|issued shares or treasury shares"
            r"|已發行股本|已發行股份或庫存股份",
            filing_title,
            re.I,
        )
        if boilerplate:
            return False
        return True
    return False


def tier_chip_forbidden(code: str, name_en: str, name_tc: str) -> bool:
    """True when a tier-1 chip is Debt and Structured Products, including a prefix.

    Contains match on the English name, the Chinese name, and the code.
    "Documents on Display" without the debt or structured-product qualifier stays.
    Monthly Returns stay in the chip list; their rows are stripped separately.
    """
    if str(code or "").strip() in DEBT_TIER_CODES:
        return True
    return contains_any(f"{name_en}\n{name_tc}", DEBT_NAME_MARKERS)


def build_tiers_document(tierone_en: list[dict], tierone_tc: list[dict]) -> dict:
    """Copy the official tier-1 list and drop debt and structured-product chips."""
    tc_by_code = {str(item.get("code", "")).strip(): item.get("name") or "" for item in tierone_tc}
    chips = []
    for item in tierone_en:
        code = str(item.get("code", "") or "").strip()
        name_en = item.get("name") or ""
        name_tc = tc_by_code.get(code, name_en)
        if tier_chip_forbidden(code, name_en, name_tc):
            continue
        chips.append({"code": code, "nameEn": name_en, "nameTc": name_tc})
    return {"tier1": chips}


def tiers_document_problems(tiers: dict) -> list[str]:
    problems = []
    chips = tiers.get("tier1") if isinstance(tiers, dict) else None
    if not isinstance(chips, list) or not chips:
        return ["tiers.json has no tier 1 chips"]
    for chip in chips:
        if not isinstance(chip, dict):
            problems.append("tiers.json has a tier chip that is not an object")
            continue
        code = str(chip.get("code", "") or "")
        name_en = str(chip.get("nameEn", "") or "")
        name_tc = str(chip.get("nameTc", "") or "")
        if tier_chip_forbidden(code, name_en, name_tc):
            problems.append(f"tiers.json still contains debt chip {code} {name_en} / {name_tc}")
    raw = json.dumps(tiers, ensure_ascii=False)
    for marker in DEBT_NAME_MARKERS:
        if marker in raw:
            problems.append(f"tiers.json contains {marker}")
    for code in sorted(DEBT_TIER_CODES):
        if f'"{code}"' in raw:
            problems.append(f"tiers.json contains code {code}")
    # Preserve order while dropping duplicate phrases from the two checks above.
    seen: set[str] = set()
    unique = []
    for item in problems:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def news_id_int(news_id: str) -> int:
    try:
        return int(str(news_id))
    except (TypeError, ValueError):
        return 0


def pdf_hyperlink(file_link: str) -> str:
    """Turn FILE_LINK into an absolute HKEXnews URL. The PDF body is not downloaded."""
    link = file_link or ""
    if link.startswith("/"):
        return PDF_BASE + link
    return link


def pair_filings(en_rows: list[dict], tc_rows: list[dict], maps) -> tuple[list[dict], dict]:
    t1e, t1c, t1e_by_code, t1c_by_code, t2e_by_t1, t2c_by_t1 = maps
    stats = {
        "paired": 0,
        "skippedStub": 0,
        "unpaired": 0,
        "rawEn": len(en_rows),
        "rawTc": len(tc_rows),
        "excludedAtBuild": 0,
        "excludedMonthlyOrNdrBuyback": 0,
    }
    tc_by_dt: dict[str, list[dict]] = defaultdict(list)
    for row in tc_rows:
        tc_by_dt[row.get("DATE_TIME") or ""].append(row)
    for rows in tc_by_dt.values():
        rows.sort(key=lambda item: news_id_int(item.get("NEWS_ID")))

    used_tc: set[Any] = set()
    paired = []
    en_sorted = sorted(en_rows, key=lambda item: (item.get("DATE_TIME") or "", news_id_int(item.get("NEWS_ID"))))

    for en in en_sorted:
        title = clean_text(en.get("TITLE") or "")
        if STUB_RE.search(title):
            stats["skippedStub"] += 1
            continue
        link = en.get("FILE_LINK") or ""
        if not link or not str(link).lower().endswith(".pdf"):
            stats["unpaired"] += 1
            continue
        cls_en = classify_row(en, t1e, t2e_by_t1)
        if is_excluded(cls_en["tier1Code"], cls_en["tier1Name"], cls_en["tier2Name"], cls_en["category"], title):
            stats["excludedAtBuild"] += 1
            stats["excludedMonthlyOrNdrBuyback"] += 1
            continue

        stamp = en.get("DATE_TIME") or ""
        en_id = news_id_int(en.get("NEWS_ID"))
        candidates = [item for item in tc_by_dt.get(stamp, []) if item.get("NEWS_ID") not in used_tc]
        if not candidates:
            stats["unpaired"] += 1
            continue

        best = None
        best_dist = 10**18
        for candidate in candidates:
            dist = abs(news_id_int(candidate.get("NEWS_ID")) - en_id)
            if dist <= 5 and dist < best_dist:
                best, best_dist = candidate, dist
        if best is None:
            for candidate in candidates:
                dist = abs(news_id_int(candidate.get("NEWS_ID")) - en_id)
                if dist <= 20 and dist < best_dist:
                    best, best_dist = candidate, dist
        if best is None:
            stats["unpaired"] += 1
            continue

        tc_link = best.get("FILE_LINK") or ""
        if not tc_link or not str(tc_link).lower().endswith(".pdf"):
            stats["unpaired"] += 1
            continue

        cls_tc = classify_row(best, t1c, t2c_by_t1)
        tc_title = clean_text(best.get("TITLE") or "")
        if is_excluded(cls_tc["tier1Code"], cls_tc["tier1Name"], cls_tc["tier2Name"], cls_tc["category"], tc_title):
            stats["excludedAtBuild"] += 1
            stats["excludedMonthlyOrNdrBuyback"] += 1
            continue

        used_tc.add(best.get("NEWS_ID"))
        tier1_code = cls_en["tier1Code"] or cls_tc["tier1Code"]
        tier1_en = cls_en["tier1Name"] or t1e_by_code.get(tier1_code, "")
        tier1_tc = cls_tc["tier1Name"] or t1c_by_code.get(tier1_code, "")
        paired.append(
            {
                "dateTime": stamp,
                "newsIdEn": str(en.get("NEWS_ID")),
                "newsIdTc": str(best.get("NEWS_ID")),
                "titleEn": title,
                "titleTc": tc_title,
                "tier1Code": tier1_code,
                "tier1En": clean_text(tier1_en),
                "tier1Tc": clean_text(tier1_tc),
                "tier2En": clean_text(cls_en["tier2Name"]),
                "tier2Tc": clean_text(cls_tc["tier2Name"]),
                "categoryEn": clean_text(cls_en["category"]),
                "categoryTc": clean_text(cls_tc["category"]),
                "pdfEn": pdf_hyperlink(link),
                "pdfTc": pdf_hyperlink(tc_link),
                "fileInfoEn": en.get("FILE_INFO") or "",
                "fileInfoTc": best.get("FILE_INFO") or "",
            }
        )
        stats["paired"] += 1

    return paired, stats


def filing_sort_key(filing: dict) -> datetime:
    try:
        return datetime.strptime(filing["dateTime"], "%d/%m/%Y %H:%M")
    except (KeyError, TypeError, ValueError):
        return datetime.min


def load_stock_maps() -> dict[str, dict]:
    paths = require_paths()
    english = json.loads((paths.data / "activestock_sehk_e.json").read_text(encoding="utf-8"))
    chinese = json.loads((paths.data / "activestock_sehk_c.json").read_text(encoding="utf-8"))
    tc_by_code = {item["c"]: item["n"] for item in chinese}
    stocks = {}
    for item in english:
        code = str(item["c"])
        if not code.isdigit():
            continue
        name_en = item["n"]
        name_tc = tc_by_code.get(code, name_en)
        if is_derivative_issuer(code, name_en, name_tc):
            continue
        stocks[code] = {
            "code": code,
            "stockId": item["i"],
            "nameEn": name_en,
            "nameTc": name_tc,
        }
    return stocks


def load_tier_lists() -> tuple[list, list, list, list]:
    paths = require_paths()
    return (
        json.loads((paths.data / "tierone_e.json").read_text(encoding="utf-8")),
        json.loads((paths.data / "tierone_c.json").read_text(encoding="utf-8")),
        json.loads((paths.data / "tiertwo_e.json").read_text(encoding="utf-8")),
        json.loads((paths.data / "tiertwo_c.json").read_text(encoding="utf-8")),
    )


def tier_maps_from_lists(tierone_en: list, tierone_tc: list, tiertwo_en: list, tiertwo_tc: list):
    t1e = {item["name"]: str(item["code"]) for item in tierone_en}
    t1c = {item["name"]: str(item["code"]) for item in tierone_tc}
    t1e_by_code = {str(item["code"]): item["name"] for item in tierone_en}
    t1c_by_code = {str(item["code"]): item["name"] for item in tierone_tc}
    t2e_by_t1: dict[str, dict] = defaultdict(dict)
    for item in tiertwo_en:
        t2e_by_t1[str(item.get("t1code"))][item["name"]] = item
    t2c_by_t1: dict[str, dict] = defaultdict(dict)
    for item in tiertwo_tc:
        t2c_by_t1[str(item.get("t1code"))][item["name"]] = item
    return t1e, t1c, t1e_by_code, t1c_by_code, t2e_by_t1, t2c_by_t1


def refresh_reference_json() -> None:
    """Pull fresh stock and tier lists into the work directory."""
    paths = require_paths()
    paths.data.mkdir(parents=True, exist_ok=True)
    for name, url in REFERENCE_URLS.items():
        time.sleep(1.5)
        code, body = http_get(url, timeout=120)
        if code != 200 or not body:
            raise RuntimeError(f"refresh {name} failed http={code}")
        json.loads(body.decode("utf-8", errors="replace"))
        dest = paths.data / name
        refuse_live_write(dest)
        dest.write_bytes(body)
        log(f"refreshed data/{name} ({len(body)} bytes)")


def row_filing_date(row: dict) -> date | None:
    raw = str(row.get("DATE_TIME") or "").strip()
    if len(raw) < 10:
        return None
    try:
        return datetime.strptime(raw[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


def rows_before(rows: list[dict], day: date) -> list[dict]:
    """Drop rows dated on or after day. Rows with no parseable date stay.

    The fresh lookback pull is merged afterwards and replaces the same NEWS_ID,
    so an undated lookback row does not keep a stale headline.
    """
    kept = []
    for row in rows:
        filed = row_filing_date(row)
        if filed is not None and filed >= day:
            continue
        kept.append(row)
    return kept


def merge_news_rows(base: list[dict], fresh: list[dict]) -> list[dict]:
    """Later rows win. A lookback pull therefore replaces a stale headline."""
    order: list[dict] = []
    index: dict[str, int] = {}
    for row in list(base) + list(fresh):
        news_id = str(row.get("NEWS_ID") or "")
        if news_id and news_id in index:
            order[index[news_id]] = row
            continue
        if news_id:
            index[news_id] = len(order)
        order.append(row)
    return order


def read_job_rows(job: Job) -> list[dict]:
    if isinstance(job, CacheJob):
        return rows_before(read_raw_json(job.lang, job.start, job.end), job.keep_before)
    return read_raw_json(job.lang, job.start, job.end)


def ingest(lang: str, rows: list[dict], store: dict[str, dict[str, dict]], equity: dict[str, dict], stats: IngestStats) -> None:
    if lang == "E":
        stats.raw_en += len(rows)
    else:
        stats.raw_tc += len(rows)
    bucket = store[lang]
    for row in rows:
        if is_derivative_filing_row(row):
            stats.skipped_derivative_rows += 1
            continue
        code = primary_code(row.get("STOCK_CODE") or "")
        if code not in equity:
            if lang == "E":
                stats.skipped_non_equity += 1
            continue
        news_id = str(row.get("NEWS_ID") or "")
        if not news_id:
            continue
        bucket.setdefault(code, {})
        # Later pull wins, so the lookback overlay replaces a stale monthly row.
        bucket[code][news_id] = row


def market_window(from_date: date, today: date) -> dict[str, str]:
    """The market-wide window stored on cache-meta.json and every issuer file."""
    return {
        "from": ymd(from_date),
        "to": ymd(today),
        "note": "Market-wide monthly titleSearch pulls; Main+GEM equity codes only",
    }


def issuer_record(info: dict, filings: list[dict], stats: dict, from_date: date, today: date) -> dict:
    return {
        "code": info["code"],
        "stockId": info["stockId"],
        "nameEn": info["nameEn"],
        "nameTc": info["nameTc"],
        "sourceWindow": market_window(from_date, today),
        "stats": stats,
        "filings": filings,
    }


def stocks_document(equity: dict[str, dict], issuers: dict[str, dict], snapshot: str) -> dict:
    """Full Main+GEM list. hasCache is the search universe that opens the feed.

    Issuers with no remaining pairs stay in the list with hasCache false, matching
    the Live stocks.json shape, and are absent from cache issuers.
    """
    has_cache = set(issuers)
    return {
        "snapshot": snapshot,
        "note": (
            "SEHK Main Board + GEM equity/ETF universe (codes 00001–09999); "
            "warrants, options, and CBBCs excluded. hasCache is true only when the "
            "issuer still has at least one paired filing after the build-time strip. "
            "Issuers with no remaining pairs are outside the hasCache universe and "
            "have no filings file. They stay in this list with hasCache false."
        ),
        "stocks": [
            {
                "c": code,
                "i": equity[code]["stockId"],
                "n": equity[code]["nameEn"],
                "nt": equity[code]["nameTc"],
                "hasCache": code in has_cache,
            }
            for code in sorted(equity)
        ],
    }


def cache_document(issuers: dict[str, dict], snapshot: str) -> dict:
    return {
        "prototypeStamp": STAMP,
        "stamp": STAMP,
        "snapshot": snapshot,
        "source": {
            "titleSearch": API,
            "stockListEn": REFERENCE_URLS["activestock_sehk_e.json"],
            "stockListTc": REFERENCE_URLS["activestock_sehk_c.json"],
            "tierOne": REFERENCE_URLS["tierone_e.json"],
            "tierTwo": REFERENCE_URLS["tiertwo_e.json"],
            "pdfBase": PDF_BASE,
        },
        "pairing": (
            "Match EN↔TC by NEWS_ID within ±5 (usually ±1) on the same DATE_TIME; "
            "fall back to closest unused same-time TC row within ±20. Drop EN stubs that only say "
            "published in Chinese. Require real PDF FILE_LINKs on both sides. Bilingual open only for paired rows."
        ),
        "note": (
            f"Beta whole-market cache from on-demand HKEXnews market-wide monthly pulls on {snapshot}. "
            "Main Board + GEM equity/ETF issuers (stock codes 00001–09999). "
            "Each incremental run re-pulls the last 14 calendar days in Asia/Hong_Kong "
            "even when the monthly raw file is already complete. "
            "Cache rows for Monthly Returns, NDR Share Buybacks, Debt and Structured Products "
            "(債券及結構性產品, including related debt and structured-product documents on display), "
            "and warrants, options, and CBBCs (牛熊證) are stripped at build (not only hidden in the UI). "
            "Metadata and FILE_LINK hyperlinks only; PDF bodies are not stored."
        ),
        "exclusions": {
            "monthlyReturns": "tier1 Monthly Returns / 月報表 / code 51500, contains match, including cancelled or reissued prefixes",
            "ndrShareBuyback": (
                "Next Day Disclosure Returns with Share Buyback in tier2 or category, "
                "or an explicit Share Buyback title; cancelled or reissued prefixes included; "
                "standard NDR form wording (and/or share buybacks) kept; AGM repurchase circulars kept"
            ),
            "debtAndStructuredProducts": (
                "tier1 Debt and Structured Products / 債券及結構性產品 / code 70000, "
                "including cancelled or reissued prefixes; also Documents on Display for "
                "debt issuance programmes (57000), debt securities (58000), and structured products (59000)"
            ),
            "warrantsOptionsCbbc": (
                "Warrants, options, and CBBCs (牛熊證 / 窩輪 / 認股證): stock codes >=10000 "
                "and derivative name markers stripped from the issuer universe and from filing rows"
            ),
            "strippedAtBuild": True,
        },
        "issuers": issuers,
    }


def cache_meta_document(issuers: dict[str, dict], snapshot: str, from_date: date, today: date) -> dict:
    """Live cache-meta.json. Counts and the window live here so the page need not load filings."""
    issuer_count, pair_count = count_pairs(issuers)
    document = cache_document(issuers, snapshot)
    document.pop("issuers", None)
    document["issuerCount"] = issuer_count
    document["pairCount"] = pair_count
    document["sourceWindow"] = market_window(from_date, today)
    return document


def issuer_code_from_path(path: Path) -> str:
    """Stock code from an issuer filename.

    Path.stem of ``03759.json.gz`` is ``03759.json``. Strip the full suffix.
    """
    name = path.name
    if name.endswith(ISSUER_GZIP_SUFFIX):
        return name[: -len(ISSUER_GZIP_SUFFIX)]
    return path.stem


def require_equity_code(code: str) -> str:
    if not (isinstance(code, str) and len(code) == 5 and code.isdigit()):
        raise RefreshError(f"issuer code {code!r} is not a five-digit stock code")
    return code


def issuer_gzip_path(root: Path, code: str) -> Path:
    require_equity_code(code)
    return root / "filings" / code[:2] / f"{code}{ISSUER_GZIP_SUFFIX}"


def compact_json_bytes(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def issuer_file_payload(record: dict, snapshot: str) -> dict:
    """One issuer file. snapshot is the same string as cache-meta.json."""
    return {
        "code": record.get("code"),
        "stockId": record.get("stockId"),
        "nameEn": record.get("nameEn"),
        "nameTc": record.get("nameTc"),
        "snapshot": snapshot,
        "sourceWindow": record.get("sourceWindow"),
        "stats": record.get("stats"),
        "filings": record.get("filings") or [],
    }


def read_gzip_payload(path: Path) -> bytes | None:
    try:
        with gzip.open(path, "rb") as handle:
            return handle.read()
    except (OSError, EOFError, gzip.BadGzipFile):
        return None


def write_gzip_file(path: Path, payload: bytes) -> None:
    refuse_live_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    refuse_live_write(tmp)
    with gzip.open(tmp, "wb", compresslevel=9) as handle:
        handle.write(payload)
    tmp.replace(path)


def sync_issuer_files(issuers: dict[str, dict], snapshot: str) -> dict[str, int]:
    """Write gzip-9 issuer files. Rewrite only when the compact payload changed.

    Unchanged files stay in place, including their mtime. Orphan files, whose
    codes are no longer in the hasCache universe, are deleted. The first run
    into an empty filings tree writes every issuer file.
    """
    paths = require_paths()
    root = paths.filings
    refuse_live_write(root)
    root.mkdir(parents=True, exist_ok=True)
    for stale in root.rglob("*.json.gz.tmp"):
        refuse_live_write(stale)
        stale.unlink()
    written = 0
    unchanged = 0
    keep: set[str] = set()
    for code, record in issuers.items():
        filings = record.get("filings") if isinstance(record, dict) else None
        if not filings:
            continue
        require_equity_code(code)
        if str(record.get("code") or "") != code:
            raise RefreshError(f"issuer key {code} does not match record code {record.get('code')!r}")
        keep.add(code)
        payload = compact_json_bytes(issuer_file_payload(record, snapshot))
        dest = issuer_gzip_path(paths.root, code)
        existing = read_gzip_payload(dest) if dest.is_file() else None
        if existing == payload:
            unchanged += 1
            continue
        write_gzip_file(dest, payload)
        written += 1
    deleted = 0
    for path in list(root.rglob("*.json.gz")):
        code = issuer_code_from_path(path)
        expected = issuer_gzip_path(paths.root, code) if len(code) == 5 and code.isdigit() else None
        misplaced = expected is None or path.resolve() != expected.resolve()
        if code not in keep or misplaced:
            refuse_live_write(path)
            path.unlink()
            deleted += 1
    for directory in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    return {"written": written, "unchanged": unchanged, "deleted": deleted}


def delete_monolith_leftovers() -> list[str]:
    """Remove a previous monolith from the work directory. Do not write a new one."""
    paths = require_paths()
    removed: list[str] = []
    for name in MONOLITH_NAMES:
        path = paths.root / name
        if path.is_file() or path.is_symlink():
            refuse_live_write(path)
            path.unlink()
            removed.append(name)
    return removed


def load_issuer_tree() -> dict[str, dict]:
    paths = require_paths()
    issuers: dict[str, dict] = {}
    if not paths.filings.exists():
        return issuers
    for path in sorted(paths.filings.rglob("*.json.gz")):
        code = issuer_code_from_path(path)
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
            loaded = {"code": code, "filings": [], "_error": str(exc)}
        if not isinstance(loaded, dict):
            loaded = {"code": code, "filings": [], "_error": "issuer file is not an object"}
        issuers[code] = loaded
    return issuers


def cache_meta_problems(meta: dict, issuers: dict) -> list[str]:
    problems = []
    if not isinstance(meta, dict):
        return ["cache-meta.json is not an object"]
    missing = [key for key in META_KEYS if key not in meta]
    if missing:
        problems.append("cache-meta.json missing " + ", ".join(missing))
    if "issuers" in meta:
        problems.append("cache-meta.json must not embed an issuers object")
    issuer_count, pair_count = count_pairs(issuers)
    if meta.get("issuerCount") != issuer_count:
        problems.append(
            f"cache-meta issuerCount {meta.get('issuerCount')} != {issuer_count} issuer files"
        )
    if meta.get("pairCount") != pair_count:
        problems.append(
            f"cache-meta pairCount {meta.get('pairCount')} != {pair_count} pairs"
        )
    window = meta.get("sourceWindow")
    if not isinstance(window, dict) or not window.get("from") or not window.get("to"):
        problems.append("cache-meta.json sourceWindow needs from and to")
    return problems


def issuer_tree_problems(meta: dict, stocks: dict, issuers: dict) -> list[str]:
    """hasCache alignment, path suffix, schema, snapshot, and no monolith."""
    problems: list[str] = []
    paths = require_paths()
    snapshot = meta.get("snapshot") if isinstance(meta, dict) else None
    meta_window = meta.get("sourceWindow") if isinstance(meta, dict) else None
    listed = stocks.get("stocks") if isinstance(stocks, dict) else None
    has_cache: set[str] = set()
    no_cache: set[str] = set()
    if isinstance(listed, list):
        for row in listed:
            if not isinstance(row, dict):
                continue
            code = str(row.get("c") or "")
            if row.get("hasCache"):
                has_cache.add(code)
            else:
                no_cache.add(code)
    found: dict[str, Path] = {}
    if paths.filings.exists():
        for path in paths.filings.rglob("*.json.gz"):
            code = issuer_code_from_path(path)
            if not (len(code) == 5 and code.isdigit()):
                problems.append(f"issuer filename {path.name} is not a five-digit code plus .json.gz")
                continue
            expected = issuer_gzip_path(paths.root, code)
            if path.resolve() != expected.resolve():
                problems.append(f"unexpected issuer path {path}")
                continue
            if code in found:
                problems.append(f"duplicate issuer file {code}")
            found[code] = path
    for code in sorted(has_cache - set(found)):
        problems.append(f"{code} hasCache is true but no issuer file was written")
    for code in sorted(set(found) & no_cache):
        problems.append(f"{code} hasCache is false but an issuer file is present")
    for code in sorted(set(found) - has_cache - no_cache):
        problems.append(f"{code} has an issuer file but is not in stocks.json")
    if set(issuers) != set(found):
        problems.append("loaded issuer codes do not match files on disk")
    for code, pack in issuers.items():
        if not isinstance(pack, dict):
            problems.append(f"{code} issuer file is not an object")
            continue
        if pack.get("_error"):
            problems.append(f"{code} issuer file could not be read ({pack['_error']})")
            continue
        missing_keys = [key for key in ISSUER_PACK_KEYS if key not in pack]
        if missing_keys:
            problems.append(f"{code} issuer file missing " + ", ".join(missing_keys))
        if pack.get("code") != code:
            problems.append(f"{code} issuer payload code is {pack.get('code')!r}")
        if snapshot and pack.get("snapshot") != snapshot:
            problems.append(f"{code} snapshot does not match cache-meta.json")
        if isinstance(meta_window, dict) and pack.get("sourceWindow") != meta_window:
            problems.append(f"{code} sourceWindow does not match cache-meta.json")
        filings = pack.get("filings")
        if not isinstance(filings, list) or not filings:
            problems.append(f"{code} issuer file has no filings")
            continue
        for row in filings:
            if not isinstance(row, dict) or any(key not in row for key in FILING_ROW_KEYS):
                problems.append(f"{code} filing row is missing the Live row keys")
                break
    for name in MONOLITH_NAMES:
        if (paths.root / name).exists():
            problems.append(f"work directory still contains {name}")
    return problems


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def hascache_problems(stocks: dict, issuers: dict) -> list[str]:
    problems = []
    if not isinstance(issuers, dict) or not isinstance(stocks, dict):
        return ["stocks.json or cache issuers are missing"]
    listed = stocks.get("stocks")
    if not isinstance(listed, list):
        return ["stocks.json has no stocks list"]
    has_cache: list[str] = []
    for stock in listed:
        if not isinstance(stock, dict):
            problems.append("stocks.json has a row that is not an object")
            continue
        code = str(stock.get("c") or "")
        filings = (issuers.get(code) or {}).get("filings") if isinstance(issuers.get(code), dict) else None
        if stock.get("hasCache"):
            has_cache.append(code)
            if code not in issuers:
                problems.append(f"{code} is in the hasCache universe but absent from issuers")
            elif not filings:
                problems.append(f"{code} is in the hasCache universe with zero pairs")
        elif code in issuers and filings:
            problems.append(f"{code} has paired filings but hasCache is false")
    for code, pack in issuers.items():
        filings = pack.get("filings") if isinstance(pack, dict) else None
        if not filings:
            problems.append(f"{code} is in issuers with zero pairs")
        elif code not in has_cache:
            problems.append(f"{code} has pairs but is outside the hasCache universe")
    return problems


def snapshot_bounds(baseline: int) -> tuple[int, int]:
    low = math.floor(baseline * (1 - SNAPSHOT_TOLERANCE))
    high = math.ceil(baseline * (1 + SNAPSHOT_TOLERANCE))
    return low, high


def counts_plausible(issuers: int, pairs: int) -> list[str]:
    """Empty, tiny, or exploded counts are not a shippable refresh of the Live snapshot."""
    low_issuers, high_issuers = snapshot_bounds(SNAPSHOT_ISSUERS)
    low_pairs, high_pairs = snapshot_bounds(SNAPSHOT_PAIRS)
    problems = []
    if issuers < low_issuers or issuers > high_issuers:
        problems.append(
            f"issuer count {issuers} is outside {low_issuers}–{high_issuers} "
            f"(±{int(SNAPSHOT_TOLERANCE * 100)}% of {SNAPSHOT_ISSUERS} issuers on {SNAPSHOT_AS_OF}, "
            "after the Debt and Structured Products strip)"
        )
    if pairs < low_pairs or pairs > high_pairs:
        problems.append(
            f"pair count {pairs} is outside {low_pairs}–{high_pairs} "
            f"(±{int(SNAPSHOT_TOLERANCE * 100)}% of {SNAPSHOT_PAIRS} pairs on {SNAPSHOT_AS_OF}, "
            "after the Debt and Structured Products strip)"
        )
    return problems


def manifest_lookback_problems(payload: dict) -> list[str]:
    try:
        today = date.fromisoformat(payload["toDate"])
        lookback_from = date.fromisoformat(payload["lookbackFrom"])
        days = int(payload["lookbackDays"])
        jobs = [job_from_dict(item) for item in payload.get("jobs") or []]
    except (KeyError, TypeError, ValueError, RefreshError) as exc:
        return [f"pull status missing a 14-day lookback plan: {exc}"]
    problems = []
    if days != LOOKBACK_DAYS:
        problems.append(f"lookbackDays is {days}, expected {LOOKBACK_DAYS}")
    expected_start = today - timedelta(days=LOOKBACK_DAYS - 1)
    if lookback_from != expected_start or (today - lookback_from).days + 1 != LOOKBACK_DAYS:
        problems.append(
            f"lookback {lookback_from.isoformat()}–{today.isoformat()} is not the last {LOOKBACK_DAYS} days"
        )
    if payload.get("fullRepull"):
        lazy = [job for job in jobs if isinstance(job, FetchJob) and not job.force]
        if lazy or any(isinstance(job, CacheJob) for job in jobs):
            problems.append("full re-pull still reuses a complete raw file")
    missing = uncovered_lookback(jobs, lookback_from, today)
    for lang, gap in missing.items():
        problems.append(
            f"{lang} lookback is not re-pulled for {len(gap)} day(s) starting {gap[0].isoformat()}"
        )
    return problems


def count_pairs(issuers: dict) -> tuple[int, int]:
    issuer_count = 0
    pair_count = 0
    for pack in issuers.values():
        filings = pack.get("filings") if isinstance(pack, dict) else None
        if not filings:
            continue
        issuer_count += 1
        pair_count += len(filings)
    return issuer_count, pair_count


def assess(
    pull_status: dict,
    cache: dict,
    stocks: dict,
    tiers: dict,
    *,
    check_snapshot: bool = True,
    read_failures: list[str] | None = None,
) -> list[str]:
    """Quality gate. A non-empty list means the build is not shippable.

    Self-test passes check_snapshot=False so a tiny fixture can prove the
    structural rules without inventing 3,072 issuers. The check command
    always compares counts with the Live snapshot.
    """
    reasons: list[str] = []
    reasons.extend(servlet_lang_problems())
    reasons.extend(manifest_lookback_problems(pull_status))
    failures = [str(item) for item in (pull_status.get("failures") or [])]
    failures.extend(str(item) for item in (read_failures or []))
    if failures:
        reasons.append(f"pulls failed ({len(failures)})")
        reasons.extend(failures[:20])
    try:
        equity_universe = int(pull_status.get("equityUniverse") or 0)
    except (TypeError, ValueError):
        equity_universe = 0
    if equity_universe <= 0:
        reasons.append("Main+GEM equity universe is empty")
    listed = stocks.get("stocks") if isinstance(stocks, dict) else None
    if isinstance(listed, list) and len(listed) != equity_universe:
        reasons.append(
            f"stocks.json lists {len(listed)} issuers but the Main+GEM equity universe is {equity_universe}"
        )
    issuers = cache.get("issuers") if isinstance(cache, dict) else None
    if not isinstance(issuers, dict):
        reasons.append("filings cache has no issuers object")
        issuers = {}
    issuer_count, pair_count = count_pairs(issuers)
    if check_snapshot:
        reasons.extend(counts_plausible(issuer_count, pair_count))
    reasons.extend(tiers_document_problems(tiers))
    reasons.extend(hascache_problems(stocks, issuers))
    return reasons


def write_progress(**kwargs: Any) -> None:
    paths = require_paths()
    payload = {"updatedAt": datetime.now(HK_TZ).strftime("%Y-%m-%d %H:%M:%S HKT"), **kwargs}
    atomic_write(paths.progress, json.dumps(payload, ensure_ascii=False, indent=2))


def run_fetches(jobs: list[Job]) -> list[str]:
    pending = [job for job in jobs if isinstance(job, FetchJob) and not job.reused_complete]
    failed: list[FetchJob] = []
    failures: list[str] = []
    for index, job in enumerate(pending, 1):
        try:
            fetch_window(job.lang, job.start, job.end, force=job.force)
            write_progress(phase="pull", jobIndex=index, jobTotal=len(pending), lang=job.lang, window=f"{ymd(job.start)}-{ymd(job.end)}")
        except Exception as exc:
            message = f"FAIL {job.lang} {job.start.isoformat()}-{job.end.isoformat()}: {exc}"
            log(message)
            traceback.print_exc()
            failed.append(job)
    if not failed:
        return []
    log(f"RETRY {len(failed)} failed windows after backoff")
    time.sleep(SLEEP_SEC * 2)
    for job in failed:
        try:
            fetch_window(job.lang, job.start, job.end, force=True)
            log(f"RETRY OK {job.lang} {job.start.isoformat()}-{job.end.isoformat()}")
        except Exception as exc:
            message = f"FAIL2 {job.lang} {job.start.isoformat()}-{job.end.isoformat()}: {exc}"
            log(message)
            traceback.print_exc()
            failures.append(message)
    return failures


def cmd_pull(full_repull: bool) -> int:
    allow_network(True)
    try:
        return _cmd_pull(full_repull)
    finally:
        allow_network(False)


def _cmd_pull(full_repull: bool) -> int:
    paths = require_paths()
    paths.raw.mkdir(parents=True, exist_ok=True)
    today = today_hkt()
    from_date = rolling_from_date(today)
    lookback_from = lookback_start(today)
    log(
        f"START pull FROM={ymd(from_date)} TO={ymd(today)} "
        f"LOOKBACK={ymd(lookback_from)}-{ymd(today)} ({LOOKBACK_DAYS} days HKT) "
        f"fullRepull={full_repull}"
    )
    try:
        http_get(REF, timeout=30)
    except Exception as exc:
        log(f"warm titlesearch warn: {exc}")
    failures: list[str] = []
    try:
        refresh_reference_json()
    except Exception as exc:
        log(f"WARN reference refresh failed, using existing data/: {exc}")
        if not (paths.data / "activestock_sehk_e.json").exists():
            failures.append(f"reference refresh failed: {exc}")
    try:
        equity = load_stock_maps()
    except Exception as exc:
        equity = {}
        failures.append(f"equity universe: {exc}")
    log(f"equity/ETF universe after warrant, option, and CBBC strip: {len(equity)}")

    def is_complete(lang: str, start: date, end: date) -> bool:
        return raw_is_complete(lang, start, end)

    jobs = plan_market(today, from_date, is_complete, full_repull=full_repull)
    assert_lookback_planned(jobs, today)
    forced = [job for job in jobs if isinstance(job, FetchJob) and job.force]
    log(f"planned jobs={len(jobs)} forced lookback or full re-pull fetches={len(forced)}")
    failures.extend(run_fetches(jobs))
    status = {
        "generatedAt": datetime.now(HK_TZ).strftime("%Y-%m-%d %H:%M:%S HKT"),
        "fromDate": from_date.isoformat(),
        "toDate": today.isoformat(),
        "lookbackFrom": lookback_from.isoformat(),
        "lookbackDays": LOOKBACK_DAYS,
        "fullRepull": full_repull,
        "equityUniverse": len(equity),
        "failures": failures,
        "jobs": [job_to_dict(job) for job in jobs],
    }
    atomic_write(paths.pull_status, json.dumps(status, ensure_ascii=False, indent=2))
    log(f"wrote {paths.pull_status.name} failures={len(failures)} equity={len(equity)}")
    if failures:
        log("PULL NOT SHIPPABLE")
        return 1
    return 0


def _pair_store(
    store: dict[str, dict[str, dict]],
    equity: dict[str, dict],
    maps,
    from_date: date,
    today: date,
) -> tuple[dict[str, dict], dict[str, int]]:
    issuers: dict[str, dict] = {}
    totals = {"paired": 0, "excluded": 0, "unpaired": 0, "stub": 0}
    codes = sorted(set(store["E"]) | set(store["C"]))
    for index, code in enumerate(codes, 1):
        filings, stats = pair_filings(
            list(store["E"].get(code, {}).values()),
            list(store["C"].get(code, {}).values()),
            maps,
        )
        filings.sort(key=filing_sort_key, reverse=True)
        totals["paired"] += stats["paired"]
        totals["excluded"] += stats["excludedAtBuild"]
        totals["unpaired"] += stats["unpaired"]
        totals["stub"] += stats["skippedStub"]
        # Zero remaining pairs: drop from issuers. stocks.json records hasCache false.
        if not filings:
            continue
        issuers[code] = issuer_record(equity[code], filings, stats, from_date, today)
        if index % 200 == 0 or index == len(codes):
            write_progress(phase="pair", issuersDone=index, issuerTotal=len(codes), totalPaired=totals["paired"])
            log(f"checkpoint pair {index}/{len(codes)} withFilings={len(issuers)} paired={totals['paired']}")
    return issuers, totals


def render_report(
    *,
    today: date,
    from_date: date,
    equity_count: int,
    issuers: dict,
    totals: dict,
    ingest: IngestStats,
    reasons: list[str],
    failures: list[str],
) -> str:
    paths = require_paths()
    lines = [
        "Bilingual HKEXnews filings — whole-market refresh report",
        f"Window: {ymd(from_date)} → {ymd(today)} (Asia/Hong_Kong)",
        f"Lookback re-pull: last {LOOKBACK_DAYS} calendar days, including today, even when the monthly raw file is complete",
        "Full three-year re-pull: about once a month, on the studio computer, via pull --full-repull. Not a GitHub Actions cron.",
        f"Stamp: {STAMP}",
        f"Equity/ETF universe (Main+GEM; warrants, options, and CBBCs stripped): {equity_count}",
        f"Issuers in the hasCache universe (paired filings > 0): {len(issuers)}",
        f"Total paired filings: {totals['paired']}",
        f"Total excluded at build (Monthly Returns, NDR Share Buybacks, Debt and Structured Products): {totals['excluded']}",
        f"Warrants, options, and CBBCs filtered (filing rows EN+TC skipped): {ingest.skipped_derivative_rows}",
        f"Non-equity EN rows skipped: {ingest.skipped_non_equity}",
        f"Total unpaired EN: {totals['unpaired']}",
        f"Total skipped stub EN: {totals['stub']}",
        f"Raw EN rows read: {ingest.raw_en}",
        f"Raw TC rows read: {ingest.raw_tc}",
        f"cache-meta.json: {paths.meta}",
        f"stocks.json: {paths.stocks}",
        f"tiers.json: {paths.tiers}",
        f"issuer files: {paths.filings}/<prefix>/<code>.json.gz (gzip-9; unchanged files are left in place)",
        "filings-cache.json and filings-cache.json.gz: not written",
        "Live site files: not written. Ship artefacts in a separate pull request.",
        "PDF bodies: not downloaded. Cache stores FILE_LINK hyperlinks only.",
        "cookies.txt: read from the work directory if present; never written by this script; not for the repository.",
    ]
    if reasons:
        lines.append(f"SHIPPABLE: NO ({len(reasons)})")
        for reason in reasons:
            lines.append(f"  - {reason}")
    else:
        lines.append("SHIPPABLE: YES")
    if failures:
        lines.append(f"PULL OR READ FAILURES ({len(failures)}):")
        for item in failures:
            lines.append(f"  - {item}")
    else:
        lines.append("PULL OR READ FAILURES: none")
    for sample in ("00700", "00005", "09988"):
        count = len(issuers.get(sample, {}).get("filings", []))
        lines.append(f"sample {sample} paired: {count}")
    return "\n".join(lines) + "\n"


def cmd_build() -> int:
    if _NETWORK_OK:
        raise RefreshError("build must not run with the network enabled")
    paths = require_paths()
    if not paths.pull_status.exists():
        raise RefreshError("No pull-status.json in the work directory. Run pull before build.")
    status = json.loads(paths.pull_status.read_text(encoding="utf-8"))
    jobs = [job_from_dict(item) for item in status.get("jobs") or []]
    today = date.fromisoformat(status["toDate"])
    from_date = date.fromisoformat(status["fromDate"])
    snapshot = snapshot_label(today)
    read_failures: list[str] = []
    try:
        equity = load_stock_maps()
    except Exception as exc:
        equity = {}
        read_failures.append(f"equity universe: {exc}")
    else:
        # The loaded list is the universe this build filtered on.
        status["equityUniverse"] = len(equity)

    tiers = {"tier1": []}
    issuers: dict[str, dict] = {}
    totals = {"paired": 0, "excluded": 0, "unpaired": 0, "stub": 0}
    ingest_stats = IngestStats()
    try:
        tier_lists = load_tier_lists()
        maps = tier_maps_from_lists(*tier_lists)
        tiers = build_tiers_document(tier_lists[0], tier_lists[1])
        store: dict[str, dict[str, dict]] = {"E": {}, "C": {}}
        for job in jobs:
            try:
                rows = read_job_rows(job)
            except (RefreshError, OSError, json.JSONDecodeError) as exc:
                read_failures.append(f"{job.lang} {job.start.isoformat()}-{job.end.isoformat()}: {exc}")
                continue
            ingest(job.lang, rows, store, equity, ingest_stats)
        issuers, totals = _pair_store(store, equity, maps, from_date, today)
    except (OSError, json.JSONDecodeError, RefreshError, KeyError) as exc:
        read_failures.append(f"build inputs: {exc}")

    stocks = stocks_document(equity, issuers, snapshot)
    meta = cache_meta_document(issuers, snapshot, from_date, today)
    cache = {"issuers": issuers}
    pull_failures = [str(item) for item in (status.get("failures") or [])]
    reasons = assess(status, cache, stocks, tiers, read_failures=read_failures)
    atomic_write(paths.meta, json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    atomic_write(paths.stocks, json.dumps(stocks, ensure_ascii=False, indent=2) + "\n")
    atomic_write(paths.tiers, json.dumps(tiers, ensure_ascii=False, indent=2) + "\n")
    # A failed or partial build must not rewrite filings/ or delete orphans.
    # The indexes above are diagnostic. The previous issuer gzip files stay.
    removed = delete_monolith_leftovers()
    sync = {"written": 0, "unchanged": 0, "deleted": 0}
    issuer_sync = False
    if reasons:
        log(
            "BUILD NOT SHIPPABLE before the issuer sync. "
            "Existing issuer gzip files were left in place."
        )
    else:
        issuer_sync = True
        sync = sync_issuer_files(issuers, snapshot)
        disk_issuers = load_issuer_tree()
        reasons.extend(cache_meta_problems(meta, disk_issuers))
        reasons.extend(issuer_tree_problems(meta, stocks, disk_issuers))
        reasons = dedupe(reasons)
    manifest = {
        "shippable": not reasons,
        "reasons": reasons,
        "readFailures": read_failures,
        "pullFailures": pull_failures,
        "equityUniverse": int(status.get("equityUniverse") or 0),
        "issuerCount": len(issuers),
        "pairCount": totals["paired"],
        "layout": "issuer-split",
        "monolith": False,
        "monolithRemoved": removed,
        "issuerSync": issuer_sync,
        "issuerFilesWritten": sync["written"],
        "issuerFilesUnchanged": sync["unchanged"],
        "issuerFilesDeleted": sync["deleted"],
        "lookbackDays": status.get("lookbackDays"),
        "fromDate": status.get("fromDate"),
        "toDate": status.get("toDate"),
        "lookbackFrom": status.get("lookbackFrom"),
        "gzip": False,
        "gzipNote": (
            "Issuer gzip files were left unchanged because this build is not shippable. "
            "No filings-cache.json.gz was written."
            if not issuer_sync
            else
            "Build writes gzip-9 issuer files in the work directory and does not write "
            "filings-cache.json.gz. gzip confirms the ship prep after the quality gate."
        ),
        "snapshotBaseline": {
            "asOf": SNAPSHOT_AS_OF,
            "issuers": SNAPSHOT_ISSUERS,
            "pairs": SNAPSHOT_PAIRS,
        },
    }
    atomic_write(paths.build_manifest, json.dumps(manifest, ensure_ascii=False, indent=2))
    report = render_report(
        today=today,
        from_date=from_date,
        equity_count=int(status.get("equityUniverse") or len(equity)),
        issuers=issuers,
        totals=totals,
        ingest=ingest_stats,
        reasons=reasons,
        failures=pull_failures + read_failures,
    )
    atomic_write(paths.report, report)
    log(report)
    write_progress(
        phase="built",
        shippable=not reasons,
        issuersWithFilings=len(issuers),
        totalPaired=totals["paired"],
        reasons=reasons,
    )
    if reasons:
        log("BUILD NOT SHIPPABLE")
        return 1
    log(
        "BUILD gate passed. "
        f"issuer files written={sync['written']} unchanged={sync['unchanged']} "
        f"deleted={sync['deleted']}. No filings-cache.json.gz was written."
    )
    return 0


def _load_built() -> tuple[dict, dict, dict, dict, dict, dict]:
    paths = require_paths()
    missing = [
        name
        for name, path in (
            ("pull-status.json", paths.pull_status),
            ("build-manifest.json", paths.build_manifest),
            ("cache-meta.json", paths.meta),
            ("stocks.json", paths.stocks),
            ("tiers.json", paths.tiers),
        )
        if not path.exists()
    ]
    if missing:
        raise RefreshError("Work directory is missing " + ", ".join(missing) + ". Run pull and build first.")
    issuers = load_issuer_tree()
    return (
        json.loads(paths.pull_status.read_text(encoding="utf-8")),
        json.loads(paths.build_manifest.read_text(encoding="utf-8")),
        {"issuers": issuers},
        json.loads(paths.stocks.read_text(encoding="utf-8")),
        json.loads(paths.tiers.read_text(encoding="utf-8")),
        json.loads(paths.meta.read_text(encoding="utf-8")),
    )


def gate_reasons(pull_status: dict, built: dict, cache: dict, stocks: dict, tiers: dict) -> list[str]:
    if "readFailures" not in built:
        extra = ["build manifest has no readFailures field"]
    else:
        extra = [f"raw read failed: {item}" for item in (built.get("readFailures") or [])]
    return assess(pull_status, cache, stocks, tiers, read_failures=extra)


def layout_reasons(meta: dict, stocks: dict, issuers: dict) -> list[str]:
    return dedupe(cache_meta_problems(meta, issuers) + issuer_tree_problems(meta, stocks, issuers))


def cmd_check() -> int:
    if _NETWORK_OK:
        raise RefreshError("check must not run with the network enabled")
    pull_status, built, cache, stocks, tiers, meta = _load_built()
    issuers = cache.get("issuers") or {}
    reasons = dedupe(gate_reasons(pull_status, built, cache, stocks, tiers) + layout_reasons(meta, stocks, issuers))
    issuer_count, pair_count = count_pairs(issuers)
    print(f"issuers {issuer_count}  pairs {pair_count}  equity {pull_status.get('equityUniverse')}")
    print(f"lookback {pull_status.get('lookbackFrom')} → {pull_status.get('toDate')} ({pull_status.get('lookbackDays')} days)")
    if reasons:
        print("SHIPPABLE: NO")
        for reason in reasons:
            print(f"  - {reason}")
        return 1
    print("SHIPPABLE: YES")
    print("Split layout is in the work directory. This check did not write filings-cache.json.gz or any Live site file.")
    return 0


def cmd_gzip() -> int:
    """Confirm the issuer-split gzip layout. Does not write a monolith, and not Live."""
    if _NETWORK_OK:
        raise RefreshError("gzip must not run with the network enabled")
    paths = require_paths()
    pull_status, built, cache, stocks, tiers, meta = _load_built()
    removed = delete_monolith_leftovers()
    issuers = cache.get("issuers") or {}
    reasons = dedupe(gate_reasons(pull_status, built, cache, stocks, tiers) + layout_reasons(meta, stocks, issuers))
    if reasons:
        print("SHIPPABLE: NO — refusing to refresh the split as a ship prep")
        for reason in reasons:
            print(f"  - {reason}")
        if removed:
            print("removed leftover monolith: " + ", ".join(removed))
        print("No filings-cache.json.gz was written.")
        return 1
    snapshot = str(meta.get("snapshot") or "")
    sync = sync_issuer_files(issuers, snapshot)
    built["gzip"] = True
    built["layout"] = "issuer-split"
    built["monolith"] = False
    built["monolithRemoved"] = removed
    built["issuerFilesWritten"] = sync["written"]
    built["issuerFilesUnchanged"] = sync["unchanged"]
    built["issuerFilesDeleted"] = sync["deleted"]
    built["gzipNote"] = (
        "Ship prep only, inside the work directory. Issuer files are gzip-9. "
        "This step does not write filings-cache.json or filings-cache.json.gz. "
        "Copying the split onto the Live site is a separate pull request."
    )
    atomic_write(paths.build_manifest, json.dumps(built, ensure_ascii=False, indent=2))
    issuer_count, pair_count = count_pairs(issuers)
    print(f"split ready: {issuer_count} issuers, {pair_count} pairs")
    print(
        f"issuer files under {paths.filings} "
        f"(written={sync['written']} unchanged={sync['unchanged']} deleted={sync['deleted']})"
    )
    if removed:
        print("removed leftover monolith: " + ", ".join(removed))
    print("No filings-cache.json.gz was written. Not a Live site file.")
    return 0


def atomic_write_bytes(path: Path, data: bytes) -> None:
    refuse_live_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    refuse_live_write(tmp)
    tmp.write_bytes(data)
    tmp.replace(path)


def cmd_all(full_repull: bool) -> int:
    pull_code = cmd_pull(full_repull)
    build_code = cmd_build()
    check_code = cmd_check()
    if pull_code == 0 and build_code == 0 and check_code == 0:
        print("all: pull, build, and check passed. Issuer gzip files are in the work directory. No monolith was written.")
        return 0
    print("all: NOT SHIPPABLE")
    return 1


def _fingerprint(path: Path) -> tuple[int, str] | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return path.stat().st_size, digest.hexdigest()


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _test_dates() -> None:
    _expect(rolling_from_date(date(2026, 11, 10)) == date(2023, 11, 10), "three-year window")
    _expect(rolling_from_date(date(2024, 2, 29)) == date(2021, 2, 28), "29 February falls back to 28 February")
    start = lookback_start(date(2026, 11, 10))
    _expect(start == date(2026, 10, 28), f"lookback start {start}")
    _expect((date(2026, 11, 10) - start).days + 1 == LOOKBACK_DAYS, "lookback is 14 inclusive days")
    _expect(len(inclusive_dates(start, date(2026, 11, 10))) == 14, "lookback date count")
    late = datetime(2026, 11, 10, 16, 30, tzinfo=ZoneInfo("UTC"))
    _expect(today_hkt(late) == date(2026, 11, 11), "16:30 UTC is the next HKT date")
    still = datetime(2026, 11, 10, 15, 59, tzinfo=ZoneInfo("UTC"))
    _expect(today_hkt(still) == date(2026, 11, 10), "15:59 UTC is still 10 November in Hong Kong")


def _test_lang() -> None:
    _expect(servlet_lang("E") == "E", "English servlet lang")
    _expect(servlet_lang("C") == "zh", "disk key C calls lang=zh")
    _expect(servlet_lang_problems() == [], "production lang map")
    _expect(servlet_lang_problems({"E": "E", "C": "C"}), "disk key must not be sent as the servlet language")
    params = search_params("C", "20261028", "20261110", 100)
    query = urlencode(params)
    forbidden_lang = "lang=" + "C"
    _expect(params["lang"] == "zh", "query lang")
    _expect("lang=zh" in query and forbidden_lang not in query, query)
    _expect(search_params("E", "20261028", "20261110", 100)["lang"] == "E", "English query")
    _expect(REF_LANG["C"] == "zh" and REF_LANG["E"] == "en", "referer languages")
    try:
        servlet_lang("zh")
    except RefreshError:
        pass
    else:
        raise AssertionError("zh is not a disk key")


def _test_lookback_plan() -> None:
    today = date(2026, 11, 10)
    from_date = rolling_from_date(today)
    lookback_from = lookback_start(today)
    complete = plan_market(today, from_date, lambda *_args: True)
    assert_lookback_planned(complete, today)
    _expect(uncovered_lookback(complete, lookback_from, today) == {}, "complete months still cover the lookback")
    for job in complete:
        if isinstance(job, FetchJob) and job.reused_complete:
            _expect(job.end < lookback_from, f"reused file overlaps lookback: {job}")
    october = [
        job
        for job in complete
        if isinstance(job, FetchJob) and job.force and job.start == date(2026, 10, 28) and job.end == date(2026, 10, 31)
    ]
    november = [
        job
        for job in complete
        if isinstance(job, FetchJob) and job.force and job.start == date(2026, 11, 1) and job.end == today
    ]
    _expect(len(october) == 2 and {job.lang for job in october} == {"E", "C"}, "October lookback slice")
    _expect(len(november) == 2 and {job.lang for job in november} == {"E", "C"}, "November lookback slice")
    september = [job for job in complete if isinstance(job, FetchJob) and job.start == date(2026, 9, 1)]
    _expect(september and all((not job.force) and job.reused_complete for job in september), "September stays cached")
    _expect(
        any(isinstance(job, CacheJob) and job.lang == "E" and job.keep_before == lookback_from and job.start == date(2026, 10, 1) for job in complete),
        "October history is read from the complete month",
    )

    fresh = plan_market(today, from_date, lambda *_args: False)
    _expect(uncovered_lookback(fresh, lookback_from, today) == {}, "incomplete months are fetched fresh")
    _expect(all(isinstance(job, FetchJob) and not job.reused_complete for job in fresh), "nothing reused when raw files are missing")
    _expect(should_reuse_raw(False, True) is True, "complete non-force reuse")
    _expect(should_reuse_raw(True, True) is False, "force ignores a complete file")
    _expect(should_reuse_raw(False, False) is False, "incomplete file is fetched")

    full = plan_market(today, from_date, lambda *_args: True, full_repull=True)
    _expect(uncovered_lookback(full, lookback_from, today) == {}, "full re-pull covers the lookback")
    _expect(all(isinstance(job, FetchJob) and job.force and not job.reused_complete for job in full), "full re-pull forces every window")

    buggy = [
        FetchJob("E", date(2026, 10, 1), date(2026, 10, 31), False, True),
        FetchJob("C", date(2026, 10, 1), date(2026, 10, 31), False, True),
        FetchJob("E", date(2026, 11, 1), today, False, True),
        FetchJob("C", date(2026, 11, 1), today, False, True),
    ]
    missing = uncovered_lookback(buggy, lookback_from, today)
    _expect(set(missing) == {"E", "C"} and len(missing["E"]) == 14, "reusing the lookback must fail")
    try:
        assert_lookback_planned(buggy, today)
    except RefreshError:
        pass
    else:
        raise AssertionError("buggy lookback plan should fail closed")

    status = {
        "toDate": today.isoformat(),
        "lookbackFrom": lookback_from.isoformat(),
        "lookbackDays": LOOKBACK_DAYS,
        "fullRepull": False,
        "jobs": [job_to_dict(job) for job in complete],
    }
    _expect(manifest_lookback_problems(status) == [], "serialized plan keeps the 14-day re-pull")
    status["jobs"] = [job_to_dict(job) for job in buggy]
    _expect(manifest_lookback_problems(status), "serialized stale plan is not shippable")


def _test_rows_overlay() -> None:
    cached = [
        {"NEWS_ID": "1", "DATE_TIME": "27/10/2026 09:00", "TITLE": "kept"},
        {"NEWS_ID": "2", "DATE_TIME": "28/10/2026 09:00", "TITLE": "stale headline"},
        {"NEWS_ID": "3", "DATE_TIME": "01/10/2026 09:00", "TITLE": "old"},
        {"NEWS_ID": "9", "DATE_TIME": "", "TITLE": "undated"},
    ]
    historical = rows_before(cached, date(2026, 10, 28))
    _expect([row["NEWS_ID"] for row in historical] == ["1", "3", "9"], "lookback rows leave the cached month")
    fresh = [
        {"NEWS_ID": "2", "DATE_TIME": "28/10/2026 09:00", "TITLE": "revised headline"},
        {"NEWS_ID": "9", "DATE_TIME": "29/10/2026 09:00", "TITLE": "undated revised"},
        {"NEWS_ID": "4", "DATE_TIME": "10/11/2026 09:00", "TITLE": "new"},
    ]
    merged = merge_news_rows(historical, fresh)
    by_id = {row["NEWS_ID"]: row["TITLE"] for row in merged}
    _expect(by_id["1"] == "kept", "pre-lookback row")
    _expect(by_id["2"] == "revised headline", "lookback headline replaced")
    _expect(by_id["3"] == "old", "older October row")
    _expect(by_id["9"] == "undated revised", "fresh NEWS_ID replaces an undated cached row")
    _expect(by_id["4"] == "new", "new lookback row")


def _mini_maps():
    tierone_en = [
        {"name": "Announcements and Notices", "code": "10000"},
        {"name": "Monthly Returns", "code": "51500"},
        {"name": "Next Day Disclosure Returns", "code": "50000"},
        {"name": "Debt and Structured Products", "code": "70000"},
        {"name": "Documents on Display", "code": "56000"},
        {"name": "Documents on Display (Debt Securities)", "code": "58000"},
    ]
    tierone_tc = [
        {"name": "公告及通告", "code": "10000"},
        {"name": "月報表", "code": "51500"},
        {"name": "翌日披露報表", "code": "50000"},
        {"name": "債券及結構性產品", "code": "70000"},
        {"name": "展示文件", "code": "56000"},
        {"name": "展示文件（債務證券）", "code": "58000"},
    ]
    return tier_maps_from_lists(tierone_en, tierone_tc, [], [])


def _row(news_id: str, title: str, long_text: str, day: str = "01/11/2026 10:00") -> dict:
    return {
        "NEWS_ID": news_id,
        "TITLE": title,
        "LONG_TEXT": long_text,
        "FILE_LINK": f"/listedco/listconews/sehk/2026/{news_id}.pdf",
        "DATE_TIME": day,
        "STOCK_CODE": "00700",
        "FILE_INFO": "10KB",
    }


def _test_exclusions_and_hascache() -> None:
    maps = _mini_maps()
    kept, stats = pair_filings(
        [_row("10", "Results announcement", "Announcements and Notices - [Results]")],
        [_row("11", "業績公告", "公告及通告 - [業績]")],
        maps,
    )
    _expect(len(kept) == 1 and stats["paired"] == 1, "ordinary pair")
    _expect(kept[0]["pdfEn"].startswith(PDF_BASE), "FILE_LINK hyperlink only")

    monthly, monthly_stats = pair_filings(
        [_row("20", "Monthly return", "Cancelled Monthly Returns - [Equity]")],
        [_row("21", "月報表", "月報表 - [股本]")],
        maps,
    )
    _expect(monthly == [] and monthly_stats["excludedAtBuild"] == 1, "prefixed Monthly Returns")

    debt, debt_stats = pair_filings(
        [_row("30", "Programme", "Reissued Debt and Structured Products - [Notice]")],
        [_row("31", "計劃", "已取消債券及結構性產品 - [通告]")],
        maps,
    )
    _expect(debt == [] and debt_stats["excludedAtBuild"] == 1, "prefixed debt tier")
    _expect(
        not "Reissued Debt and Structured Products".startswith("Debt and Structured Products"),
        "fixture really is a prefix, not an exact title",
    )

    display, display_stats = pair_filings(
        [_row("32", "Display", "Documents on Display (Debt Securities) - [Offering]")],
        [_row("33", "展示", "展示文件（債務證券） - [發售]")],
        maps,
    )
    _expect(display == [] and display_stats["excludedAtBuild"] == 1, "debt documents on display")

    plain_display, plain_stats = pair_filings(
        [_row("34", "Display", "Documents on Display - [Contracts]")],
        [_row("35", "展示", "展示文件 - [合約]")],
        maps,
    )
    _expect(len(plain_display) == 1 and plain_stats["excludedAtBuild"] == 0, "ordinary documents on display stay")

    ndr_form, ndr_stats = pair_filings(
        [_row("40", "Next Day Disclosure Return - changes in issued share capital and/or share buybacks", "Next Day Disclosure Returns - [Others]")],
        [_row("41", "翌日披露報表 - 已發行股本及/或股份購回的變動", "翌日披露報表 - [其他]")],
        maps,
    )
    _expect(len(ndr_form) == 1 and ndr_stats["excludedAtBuild"] == 0, "standard NDR form stays")

    buyback, buyback_stats = pair_filings(
        [_row("42", "Share Buyback", "Next Day Disclosure Returns - [Share Buyback]")],
        [_row("43", "股份購回", "翌日披露報表 - [股份購回]")],
        maps,
    )
    _expect(buyback == [] and buyback_stats["excludedAtBuild"] == 1, "NDR share buyback")

    agm, agm_stats = pair_filings(
        [_row("44", "Proposed general mandate and share repurchase", "Circulars - [Repurchase Mandate]")],
        [_row("45", "建議購回授權", "通函 - [購回授權]")],
        maps,
    )
    _expect(len(agm) == 1 and agm_stats["excludedAtBuild"] == 0, "AGM repurchase circular stays")

    equity = {
        "00700": {"code": "00700", "stockId": 1, "nameEn": "TENCENT", "nameTc": "騰訊"},
        "00001": {"code": "00001", "stockId": 2, "nameEn": "CKH", "nameTc": "長和"},
    }
    issuers = {
        "00700": issuer_record(equity["00700"], kept, {"paired": 1}, date(2023, 11, 10), date(2026, 11, 10)),
    }
    stocks = stocks_document(equity, issuers, snapshot_label(date(2026, 11, 10)))
    by_code = {row["c"]: row for row in stocks["stocks"]}
    _expect(by_code["00700"]["hasCache"] is True, "paired issuer is in the hasCache universe")
    _expect(by_code["00001"]["hasCache"] is False, "zero-pair issuer is outside the hasCache universe")
    _expect("00001" not in issuers, "zero-pair issuer is absent from issuers")
    _expect("filings-cache.json" not in stocks["note"], "stocks note no longer names the monolith")
    _expect(hascache_problems(stocks, issuers) == [], "consistent hasCache fixture")
    broken = json.loads(json.dumps(stocks))
    for row in broken["stocks"]:
        if row["c"] == "00001":
            row["hasCache"] = True
    _expect(hascache_problems(broken, issuers), "hasCache without pairs must fail")
    empty_issuer = dict(issuers)
    empty_issuer["00001"] = issuer_record(equity["00001"], [], {}, date(2023, 11, 10), date(2026, 11, 10))
    _expect(hascache_problems(stocks, empty_issuer), "empty issuers entry must fail")
    _expect(is_derivative_issuer("10000") is True, "derivative code")
    _expect(is_derivative_issuer("00700", "TENCENT", "騰訊") is False, "ordinary equity")
    _expect(is_derivative_filing_row({"STOCK_NAME": "ABC CBBC", "STOCK_CODE": "00700"}) is True, "CBBC row")


def _test_tiers() -> None:
    official_en = [
        {"code": "10000", "name": "Announcements and Notices"},
        {"code": "51500", "name": "Monthly Returns"},
        {"code": "50000", "name": "Next Day Disclosure Returns"},
        {"code": "56000", "name": "Documents on Display"},
        {"code": "70000", "name": "Debt and Structured Products"},
        {"code": "57000", "name": "Documents on Display (Debt Issuance Programmes)"},
        {"code": "58000", "name": "Documents on Display (Debt Securities)"},
        {"code": "59000", "name": "Documents on Display (Structured Products)"},
        {"code": "70001", "name": "Cancelled Debt and Structured Products"},
        {"code": "70002", "name": "Reissued - 債券及結構性產品"},
        {"code": "58001", "name": "(Cancelled) Documents on Display (Debt Securities)"},
        {"code": "10001", "name": "Announcements and Notices"},
    ]
    official_tc = [
        {"code": "10000", "name": "公告及通告"},
        {"code": "51500", "name": "月報表"},
        {"code": "50000", "name": "翌日披露報表"},
        {"code": "56000", "name": "展示文件"},
        {"code": "70000", "name": "債券及結構性產品"},
        {"code": "57000", "name": "展示文件（債務證券發行計劃）"},
        {"code": "58000", "name": "展示文件（債務證券）"},
        {"code": "59000", "name": "展示文件（結構性產品）"},
        {"code": "70001", "name": "已取消債券及結構性產品"},
        {"code": "70002", "name": "重新發出 債券及結構性產品"},
        {"code": "58001", "name": "展示文件（債務證券）"},
        {"code": "10001", "name": "已取消 債券及結構性產品"},
    ]
    _expect(
        not official_en[8]["name"].startswith("Debt and Structured Products"),
        "cancelled chip is a prefix",
    )
    document = build_tiers_document(official_en, official_tc)
    codes = [chip["code"] for chip in document["tier1"]]
    _expect(codes == ["10000", "51500", "50000", "56000"], codes)
    _expect(tiers_document_problems(document) == [], "stripped tiers pass")
    dirty = {
        "tier1": [
            {"code": "10000", "nameEn": "Announcements and Notices", "nameTc": "公告及通告"},
            {"code": "70000", "nameEn": "Debt and Structured Products", "nameTc": "債券及結構性產品"},
        ]
    }
    _expect(tiers_document_problems(dirty), "70000 must fail the gate")
    prefixed = {
        "tier1": [
            {"code": "10000", "nameEn": "Announcements and Notices", "nameTc": "公告及通告"},
            {"code": "12345", "nameEn": "Reissued Debt and Structured Products", "nameTc": "公告及通告"},
        ]
    }
    _expect(tiers_document_problems(prefixed), "prefixed English name must fail the gate")


def _clean_pull_status() -> dict:
    today = date(2026, 11, 10)
    jobs = plan_market(today, rolling_from_date(today), lambda *_args: True)
    return {
        "fromDate": rolling_from_date(today).isoformat(),
        "toDate": today.isoformat(),
        "lookbackFrom": lookback_start(today).isoformat(),
        "lookbackDays": LOOKBACK_DAYS,
        "fullRepull": False,
        "equityUniverse": 2,
        "failures": [],
        "jobs": [job_to_dict(job) for job in jobs],
    }


def _clean_fixture():
    today = date(2026, 11, 10)
    equity = {
        "00700": {"code": "00700", "stockId": 1, "nameEn": "TENCENT", "nameTc": "騰訊"},
        "00001": {"code": "00001", "stockId": 2, "nameEn": "CKH", "nameTc": "長和"},
    }
    filing = {
        "dateTime": "01/11/2026 10:00",
        "titleEn": "Results",
        "titleTc": "業績",
        "tier1Code": "10000",
        "tier1En": "Announcements and Notices",
        "tier1Tc": "公告及通告",
        "pdfEn": PDF_BASE + "/a.pdf",
        "pdfTc": PDF_BASE + "/b.pdf",
    }
    issuers = {"00700": issuer_record(equity["00700"], [filing], {"paired": 1}, rolling_from_date(today), today)}
    tiers = build_tiers_document(
        [
            {"code": "10000", "name": "Announcements and Notices"},
            {"code": "70000", "name": "Debt and Structured Products"},
            {"code": "51500", "name": "Monthly Returns"},
        ],
        [
            {"code": "10000", "name": "公告及通告"},
            {"code": "70000", "name": "債券及結構性產品"},
            {"code": "51500", "name": "月報表"},
        ],
    )
    stocks = stocks_document(equity, issuers, snapshot_label(today))
    cache = cache_document(issuers, snapshot_label(today))
    return _clean_pull_status(), cache, stocks, tiers


def _test_gate() -> None:
    low_issuers, high_issuers = snapshot_bounds(SNAPSHOT_ISSUERS)
    low_pairs, high_pairs = snapshot_bounds(SNAPSHOT_PAIRS)
    _expect(counts_plausible(SNAPSHOT_ISSUERS, SNAPSHOT_PAIRS) == [], "baseline counts")
    _expect(counts_plausible(low_issuers, low_pairs) == [], "lower bound")
    _expect(counts_plausible(high_issuers, high_pairs) == [], "upper bound")
    _expect(counts_plausible(low_issuers - 1, SNAPSHOT_PAIRS), "issuer count below the band")
    _expect(counts_plausible(SNAPSHOT_ISSUERS, low_pairs - 1), "pair count below the band")
    _expect(counts_plausible(10, 10), "tiny counts are implausible")

    status, cache, stocks, tiers = _clean_fixture()
    _expect("70000" not in json.dumps(tiers), "fixture tiers dropped 70000")
    structural = assess(status, cache, stocks, tiers, check_snapshot=False)
    _expect(structural == [], structural)
    implausible = assess(status, cache, stocks, tiers, check_snapshot=True)
    _expect(any("issuer count" in reason for reason in implausible), implausible)

    failed = dict(status)
    failed["failures"] = ["FAIL E 2026-11-01-2026-11-10: http 503"]
    _expect(any("pulls failed" in reason for reason in assess(failed, cache, stocks, tiers, check_snapshot=False)), "failed pull")

    empty_equity = dict(status)
    empty_equity["equityUniverse"] = 0
    _expect(
        any("equity universe is empty" in reason for reason in assess(empty_equity, cache, stocks, tiers, check_snapshot=False)),
        "empty universe",
    )

    dirty_tiers = {"tier1": list(tiers["tier1"]) + [{"code": "59000", "nameEn": "Documents on Display (Structured Products)", "nameTc": "展示文件（結構性產品）"}]}
    _expect(assess(status, cache, stocks, dirty_tiers, check_snapshot=False), "debt chip fails assess")

    broken_stocks = json.loads(json.dumps(stocks))
    for row in broken_stocks["stocks"]:
        if row["c"] == "00001":
            row["hasCache"] = True
    _expect(assess(status, cache, broken_stocks, tiers, check_snapshot=False), "zero-pair hasCache fails assess")


def _sample_filing(title: str) -> dict:
    return {
        "dateTime": "11/11/2026 16:42",
        "newsIdEn": "12403546",
        "newsIdTc": "12403547",
        "titleEn": title,
        "titleTc": "標題",
        "tier1Code": "10000",
        "tier1En": "Announcements and Notices",
        "tier1Tc": "公告及通告",
        "tier2En": "Results",
        "tier2Tc": "業績",
        "categoryEn": "Announcements and Notices - [Results]",
        "categoryTc": "公告及通告 - [業績]",
        "pdfEn": PDF_BASE + "/listedco/a.pdf",
        "pdfTc": PDF_BASE + "/listedco/a_c.pdf",
        "fileInfoEn": "10KB",
        "fileInfoTc": "12KB",
    }


def _test_split_write() -> None:
    """Offline split layout: paths, schema, incremental rewrite, orphans, no monolith."""
    import tempfile

    today = date(2026, 11, 11)
    from_date = date(2023, 11, 11)
    snapshot = snapshot_label(today)
    _expect(snapshot == "11 November 2026 (Asia/Hong_Kong)", snapshot)
    _expect(issuer_code_from_path(Path("filings/03/03759.json.gz")) == "03759", "strip the full .json.gz suffix")
    _expect(Path("filings/03/03759.json.gz").stem == "03759.json", "Path.stem leaves a .json leftover")
    _expect(list(META_KEYS) == [
        "prototypeStamp",
        "stamp",
        "snapshot",
        "source",
        "pairing",
        "note",
        "exclusions",
        "issuerCount",
        "pairCount",
        "sourceWindow",
    ], "cache-meta key order")

    equity = {
        "00001": {"code": "00001", "stockId": 1, "nameEn": "CKH HOLDINGS", "nameTc": "長和"},
        "00002": {"code": "00002", "stockId": 2, "nameEn": "CLP HOLDINGS", "nameTc": "中電控股"},
        "03759": {"code": "03759", "stockId": 3759, "nameEn": "EXAMPLE", "nameTc": "例子"},
    }
    issuers = {
        "00001": issuer_record(equity["00001"], [_sample_filing("First")], {"paired": 1}, from_date, today),
        "03759": issuer_record(equity["03759"], [_sample_filing("Other")], {"paired": 1}, from_date, today),
    }
    with tempfile.TemporaryDirectory() as tmp:
        paths = configure(Path(tmp))
        (paths.root / "filings-cache.json").write_text("{}\n", encoding="utf-8")
        (paths.root / "filings-cache.json.gz").write_bytes(gzip.compress(b"{}"))
        (paths.root / "filings-cache.partial.json").write_text("{}\n", encoding="utf-8")
        meta = cache_meta_document(issuers, snapshot, from_date, today)
        stocks = stocks_document(equity, issuers, snapshot)
        _expect("filings-cache.json" not in stocks["note"], stocks["note"])
        _expect(meta["issuerCount"] == 2 and meta["pairCount"] == 2, meta)
        _expect(list(meta.keys()) == list(META_KEYS), list(meta.keys()))
        _expect("issuers" not in meta, "cache-meta does not embed issuers")
        atomic_write(paths.meta, json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
        atomic_write(paths.stocks, json.dumps(stocks, ensure_ascii=False, indent=2) + "\n")
        first = sync_issuer_files(issuers, snapshot)
        _expect(first == {"written": 2, "unchanged": 0, "deleted": 0}, first)
        removed = delete_monolith_leftovers()
        _expect(removed == ["filings-cache.json", "filings-cache.json.gz", "filings-cache.partial.json"], removed)
        for name in MONOLITH_NAMES:
            _expect(not (paths.root / name).exists(), name)
        path_00001 = issuer_gzip_path(paths.root, "00001")
        path_03759 = issuer_gzip_path(paths.root, "03759")
        _expect(path_00001.is_file() and path_00001.parent.name == "00" and path_00001.name == "00001.json.gz", str(path_00001))
        _expect(path_03759.is_file() and path_03759.parent.name == "03" and path_03759.name == "03759.json.gz", str(path_03759))
        _expect(not (paths.filings / "03" / "03759.json").exists(), "do not keep the Path.stem leftover")
        _expect(not issuer_gzip_path(paths.root, "00002").exists(), "hasCache false has no issuer file")
        _expect(path_00001.read_bytes()[:2] == b"\x1f\x8b", "issuer file is gzip")
        pack = json.loads(gzip.decompress(path_03759.read_bytes()))
        _expect(list(pack.keys()) == list(ISSUER_PACK_KEYS), list(pack.keys()))
        _expect(pack["code"] == "03759" and pack["snapshot"] == meta["snapshot"] == snapshot, pack.get("snapshot"))
        _expect(pack["sourceWindow"] == meta["sourceWindow"], "issuer sourceWindow matches cache-meta")
        _expect(list(pack["filings"][0].keys()) == list(FILING_ROW_KEYS), list(pack["filings"][0].keys()))
        by_code = {row["c"]: row["hasCache"] for row in stocks["stocks"]}
        _expect(by_code == {"00001": True, "00002": False, "03759": True}, by_code)
        disk = load_issuer_tree()
        _expect(set(disk) == {"00001", "03759"}, set(disk))
        _expect(layout_reasons(meta, stocks, disk) == [], layout_reasons(meta, stocks, disk))
        misplaced = paths.filings / "99" / "03759.json.gz"
        misplaced.parent.mkdir()
        misplaced.write_bytes(path_03759.read_bytes())
        fixed = sync_issuer_files(issuers, snapshot)
        _expect(fixed == {"written": 0, "unchanged": 2, "deleted": 1}, fixed)
        _expect(not misplaced.exists(), "misplaced prefix is not a second copy of the issuer")
        _expect(not (paths.filings / "99").exists(), "empty wrong prefix directory removed")

        mtime_00001 = path_00001.stat().st_mtime_ns
        mtime_03759 = path_03759.stat().st_mtime_ns
        second = sync_issuer_files(issuers, snapshot)
        _expect(second == {"written": 0, "unchanged": 2, "deleted": 0}, second)
        _expect(path_00001.stat().st_mtime_ns == mtime_00001, "unchanged gzip left in place")
        _expect(path_03759.stat().st_mtime_ns == mtime_03759, "second unchanged gzip left in place")
        roundtrip = sync_issuer_files(load_issuer_tree(), snapshot)
        _expect(roundtrip == {"written": 0, "unchanged": 2, "deleted": 0}, roundtrip)
        _expect(path_00001.stat().st_mtime_ns == mtime_00001, "reloaded payload did not rewrite the gzip")

        revised = {
            "00001": issuers["00001"],
            "03759": issuer_record(equity["03759"], [_sample_filing("Revised")], {"paired": 1}, from_date, today),
        }
        third = sync_issuer_files(revised, snapshot)
        _expect(third == {"written": 1, "unchanged": 1, "deleted": 0}, third)
        _expect(path_00001.stat().st_mtime_ns == mtime_00001, "untouched issuer kept its mtime")
        _expect(json.loads(gzip.decompress(path_03759.read_bytes()))["filings"][0]["titleEn"] == "Revised", "changed issuer payload rewritten")

        only = {"03759": revised["03759"]}
        stocks_after = stocks_document(equity, only, snapshot)
        fourth = sync_issuer_files(only, snapshot)
        _expect(fourth == {"written": 0, "unchanged": 1, "deleted": 1}, fourth)
        _expect(not path_00001.exists(), "orphan issuer file deleted")
        _expect(not (paths.filings / "00").exists(), "empty prefix directory removed")
        _expect(path_03759.is_file(), "remaining issuer file kept")
        _expect(not issuer_gzip_path(paths.root, "00002").exists(), "still no file for hasCache false")
        meta_after = cache_meta_document(only, snapshot, from_date, today)
        _expect(meta_after["issuerCount"] == 1 and meta_after["pairCount"] == 1, meta_after)
        disk_after = load_issuer_tree()
        _expect(layout_reasons(meta_after, stocks_after, disk_after) == [], layout_reasons(meta_after, stocks_after, disk_after))
        after_flags = {row["c"]: row["hasCache"] for row in stocks_after["stocks"]}
        _expect(after_flags["00001"] is False and after_flags["03759"] is True and after_flags["00002"] is False, after_flags)
        broken = json.loads(json.dumps(stocks_after))
        for row in broken["stocks"]:
            if row["c"] == "00002":
                row["hasCache"] = True
        broken_reasons = issuer_tree_problems(meta_after, broken, disk_after)
        _expect(any("00002" in item and "hasCache is true" in item for item in broken_reasons), broken_reasons)
        for name in MONOLITH_NAMES:
            _expect(not (paths.root / name).exists(), name)
        tiers = build_tiers_document(
            [{"code": "10000", "name": "Announcements and Notices"}],
            [{"code": "10000", "name": "公告及通告"}],
        )
        atomic_write(paths.tiers, json.dumps(tiers, ensure_ascii=False, indent=2) + "\n")
        atomic_write(paths.meta, json.dumps(meta_after, ensure_ascii=False, indent=2) + "\n")
        atomic_write(paths.stocks, json.dumps(stocks_after, ensure_ascii=False, indent=2) + "\n")
        status = _clean_pull_status()
        status["equityUniverse"] = 3
        atomic_write(paths.pull_status, json.dumps(status) + "\n")
        atomic_write(paths.build_manifest, json.dumps({"readFailures": [], "gzip": False}) + "\n")
        (paths.root / "filings-cache.json.gz").write_bytes(gzip.compress(b"{}"))
        import io
        from contextlib import redirect_stdout

        with redirect_stdout(io.StringIO()):
            gzip_code = cmd_gzip()
        _expect(gzip_code == 1, "a tiny fixture is outside the Live count band")
        _expect(not (paths.root / "filings-cache.json").exists(), "gzip did not write a monolith")
        _expect(not (paths.root / "filings-cache.json.gz").exists(), "gzip removed the monolith and did not write a new one")
        _expect(path_03759.is_file(), "refused gzip left the issuer file in place")
    global PATHS
    PATHS = None


def _seed_equity_and_tiers(codes: list[tuple[str, int, str, str]]) -> None:
    paths = require_paths()
    paths.data.mkdir(parents=True, exist_ok=True)
    english = [{"c": code, "i": stock_id, "n": name_en} for code, stock_id, name_en, _name_tc in codes]
    chinese = [{"c": code, "i": stock_id, "n": name_tc} for code, stock_id, _name_en, name_tc in codes]
    (paths.data / "activestock_sehk_e.json").write_text(json.dumps(english), encoding="utf-8")
    (paths.data / "activestock_sehk_c.json").write_text(json.dumps(chinese), encoding="utf-8")
    (paths.data / "tierone_e.json").write_text(
        json.dumps([{"name": "Announcements and Notices", "code": "10000"}]),
        encoding="utf-8",
    )
    (paths.data / "tierone_c.json").write_text(
        json.dumps([{"name": "公告及通告", "code": "10000"}]),
        encoding="utf-8",
    )
    (paths.data / "tiertwo_e.json").write_text("[]", encoding="utf-8")
    (paths.data / "tiertwo_c.json").write_text("[]", encoding="utf-8")


def _write_complete_raw(lang: str, start: date, end: date, rows: list[dict]) -> None:
    path = raw_path(lang, start, end)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    path.with_suffix(".meta.json").write_text(json.dumps({"complete": True}), encoding="utf-8")


def _issuer_fingerprints(codes: list[str]) -> dict[str, tuple[int, str] | None]:
    paths = require_paths()
    return {code: _fingerprint(issuer_gzip_path(paths.root, code)) for code in codes}


def _test_failed_build_preserves_issuer_files() -> None:
    """A non-shippable build or gzip must not rewrite or delete issuer gzip files."""
    import io
    import tempfile
    from contextlib import redirect_stdout

    today = date(2026, 11, 10)
    from_date = rolling_from_date(today)
    snapshot = snapshot_label(today)
    equity_rows = [
        ("00001", 1, "CKH HOLDINGS", "長和"),
        ("00700", 700, "TENCENT", "騰訊"),
        ("03759", 3759, "EXAMPLE", "例子"),
    ]
    equity = {
        code: {"code": code, "stockId": stock_id, "nameEn": name_en, "nameTc": name_tc}
        for code, stock_id, name_en, name_tc in equity_rows
    }
    kept = {
        code: issuer_record(equity[code], [_sample_filing(f"Kept {code}")], {"paired": 1}, from_date, today)
        for code in equity
    }

    def plant(paths: WorkPaths) -> dict[str, tuple[int, str] | None]:
        sync_issuer_files(kept, snapshot)
        (paths.root / "filings-cache.json").write_text("{}\n", encoding="utf-8")
        (paths.root / "filings-cache.json.gz").write_bytes(gzip.compress(b"{}"))
        return _issuer_fingerprints(list(equity))

    with tempfile.TemporaryDirectory() as tmp:
        paths = configure(Path(tmp))
        _seed_equity_and_tiers(equity_rows)
        before = plant(paths)
        status = _clean_pull_status()
        status["equityUniverse"] = 3
        en_row = _row("100", "Replaced", "Announcements and Notices - [Results]", "01/06/2024 10:00")
        tc_row = _row("101", "已更換", "公告及通告 - [業績]", "01/06/2024 10:00")
        en_row["STOCK_CODE"] = "00001"
        tc_row["STOCK_CODE"] = "00001"
        for job in (job_from_dict(item) for item in status["jobs"]):
            _write_complete_raw(job.lang, job.start, job.end, [en_row if job.lang == "E" else tc_row])
        atomic_write(paths.pull_status, json.dumps(status) + "\n")
        with redirect_stdout(io.StringIO()):
            build_code = cmd_build()
        _expect(build_code == 1, "partial pair store is outside the Live count band")
        manifest = json.loads(paths.build_manifest.read_text(encoding="utf-8"))
        _expect(manifest.get("issuerSync") is False, manifest.get("issuerSync"))
        _expect(manifest.get("issuerFilesDeleted") == 0, manifest.get("issuerFilesDeleted"))
        _expect(manifest.get("issuerFilesWritten") == 0, manifest.get("issuerFilesWritten"))
        _expect(_issuer_fingerprints(list(equity)) == before, "partial build rewrote or deleted issuer files")
        _expect(issuer_gzip_path(paths.root, "00700").is_file(), "partial build deleted an issuer absent from the pair store")
        _expect("Kept 00001" in gzip.decompress(issuer_gzip_path(paths.root, "00001").read_bytes()).decode("utf-8"), "partial build rewrote a kept issuer")
        for name in MONOLITH_NAMES:
            if name == "filings-cache.partial.json":
                continue
            _expect(not (paths.root / name).exists(), f"failed build left {name}")
        (paths.root / "filings-cache.json.gz").write_bytes(gzip.compress(b"{}"))
        with redirect_stdout(io.StringIO()):
            gzip_code = cmd_gzip()
        _expect(gzip_code == 1, "gzip must refuse a partial build")
        _expect(_issuer_fingerprints(list(equity)) == before, "refused gzip rewrote or deleted issuer files")
        _expect(not (paths.root / "filings-cache.json.gz").exists(), "refused gzip left a monolith")

    with tempfile.TemporaryDirectory() as tmp:
        paths = configure(Path(tmp))
        _seed_equity_and_tiers(equity_rows)
        before = plant(paths)
        status = _clean_pull_status()
        status["equityUniverse"] = 3
        status["failures"] = ["FAIL E 2026-11-01-2026-11-10: http 503"]
        atomic_write(paths.pull_status, json.dumps(status) + "\n")
        with redirect_stdout(io.StringIO()):
            build_code = cmd_build()
        _expect(build_code == 1, "pull failure is not shippable")
        manifest = json.loads(paths.build_manifest.read_text(encoding="utf-8"))
        _expect(manifest.get("issuerSync") is False, "pull failure still synced issuer files")
        _expect(any("pulls failed" in reason for reason in manifest.get("reasons") or []), manifest.get("reasons"))
        _expect(_issuer_fingerprints(list(equity)) == before, "pull failure rewrote or deleted issuer files")

    with tempfile.TemporaryDirectory() as tmp:
        paths = configure(Path(tmp))
        before = plant(paths)
        status = _clean_pull_status()
        status["equityUniverse"] = 0
        atomic_write(paths.pull_status, json.dumps(status) + "\n")
        with redirect_stdout(io.StringIO()):
            build_code = cmd_build()
        _expect(build_code == 1, "empty equity universe is not shippable")
        manifest = json.loads(paths.build_manifest.read_text(encoding="utf-8"))
        _expect(manifest.get("issuerSync") is False, "empty universe still synced issuer files")
        _expect(any("equity universe is empty" in reason for reason in manifest.get("reasons") or []), manifest.get("reasons"))
        _expect(_issuer_fingerprints(list(equity)) == before, "empty universe rewrote or deleted issuer files")

    global PATHS
    PATHS = None


def _test_network_and_live_guard(before: dict[Path, tuple[int, str] | None]) -> None:
    _expect(_NETWORK_OK is False, "network starts disabled")
    try:
        http_get(API)
    except RuntimeError as exc:
        _expect("blocked" in str(exc).lower(), str(exc))
    else:
        raise AssertionError("self-test must not call HKEXnews")
    try:
        configure(REPO_ROOT)
    except RefreshError as exc:
        _expect("Live" in str(exc), str(exc))
    else:
        raise AssertionError("repo root must not be a work directory")
    try:
        atomic_write(REPO_ROOT / "stocks.json", "{}")
    except RefreshError:
        pass
    else:
        raise AssertionError("atomic_write must refuse Live stocks.json")
    try:
        atomic_write(REPO_ROOT / "cache-meta.json", "{}")
    except RefreshError:
        pass
    else:
        raise AssertionError("atomic_write must refuse Live cache-meta.json")
    try:
        atomic_write_bytes(REPO_ROOT / "filings" / "00" / "00001.json.gz", b"nope")
    except RefreshError:
        pass
    else:
        raise AssertionError("atomic_write_bytes must refuse a Live issuer file")
    try:
        configure(REPO_ROOT / "filings")
    except RefreshError:
        pass
    else:
        raise AssertionError("the Live filings tree must not be a work directory")
    source = Path(__file__).read_text(encoding="utf-8")
    # Build the banned tokens here so the check is not tripped by its own source line.
    chinese_site_name = chr(0x62AB) + chr(0x9732) + chr(0x6613)
    forbidden_lang = "lang=" + "C"
    _expect(chinese_site_name not in source, "English copy uses HKEXnews rather than the Chinese site name")
    _expect(forbidden_lang not in source, "servlet URLs must not send the disk key as the language")
    _expect(("application/" + "pdf") not in source, "no PDF body download")
    ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    _expect("data/hkex-filings-work/" in ignore and "cookies.txt" in ignore, "work directory and cookies are gitignored")
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        paths = configure(Path(tmp))
        _expect(paths.stocks.parent == Path(tmp).resolve(), "work outputs stay in the work directory")
        _expect(not paths.cookie.exists(), "cookies.txt is not created")
        refuse_live_write(paths.stocks)
    global PATHS
    PATHS = None
    _expect(before[REPO_ROOT / "stocks.json"] == _fingerprint(REPO_ROOT / "stocks.json"), "stocks.json unchanged during guard checks")


def self_test() -> None:
    watched = [
        REPO_ROOT / "stocks.json",
        REPO_ROOT / "tiers.json",
        REPO_ROOT / "cache-meta.json",
        REPO_ROOT / "filings" / "00" / "00001.json.gz",
        REPO_ROOT / "filings" / "02" / "02688.json.gz",
        REPO_ROOT / "filings-cache.json.gz",
        REPO_ROOT / "filings-cache.json",
        REPO_ROOT / "bilingual-hkex-filings.html",
        REPO_ROOT / "bilingual-hkex-viewer.html",
        REPO_ROOT / "index.html",
        REPO_ROOT / "board-meeting-heatmap.html",
        REPO_ROOT / "language-watchdog.html",
    ]
    before = {path: _fingerprint(path) for path in watched}
    work_existed = DEFAULT_WORK.exists()
    _test_dates()
    _test_lang()
    _test_lookback_plan()
    _test_rows_overlay()
    _test_exclusions_and_hascache()
    _test_tiers()
    _test_gate()
    _test_split_write()
    _test_failed_build_preserves_issuer_files()
    _test_network_and_live_guard(before)
    after = {path: _fingerprint(path) for path in watched}
    if before != after:
        changed = [str(path.relative_to(REPO_ROOT)) for path in watched if before[path] != after[path]]
        raise AssertionError("self-test changed Live site files: " + ", ".join(changed))
    if not work_existed and DEFAULT_WORK.exists():
        raise AssertionError("self-test created the work directory")
    print("self-test ok")


def parse_args(argv: list[str]) -> tuple[argparse.ArgumentParser, argparse.Namespace]:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--work",
        type=Path,
        default=None,
        help="work directory (default: data/hkex-filings-work or HKEX_FILINGS_ROOT). Never the repo root.",
    )
    parser = argparse.ArgumentParser(
        description="Refresh the bilingual HKEXnews filings cache into a local work directory.",
        epilog=(
            "No command starts a pull. Run --self-test, or pull, then build, then check. "
            "build writes the issuer-split gzip files. gzip confirms that ship prep and "
            "does not write a monolith. See scripts/bilingual-hkex-filings.md."
        ),
    )
    parser.add_argument("--self-test", action="store_true", help="run offline checks and exit (no HKEXnews, no Live writes)")
    sub = parser.add_subparsers(dest="command")
    pull = sub.add_parser("pull", parents=[common], help="refresh reference lists and raw title-search windows")
    pull.add_argument("--full-repull", action="store_true", help="ignore complete raw files and re-pull the three-year window")
    sub.add_parser("build", parents=[common], help="pair, strip, and write the issuer-split cache in the work directory")
    sub.add_parser("check", parents=[common], help="quality gate; exit 1 when the build is not shippable")
    sub.add_parser("gzip", parents=[common], help="ship prep: confirm gzip-9 issuer files; do not write a monolith")
    everything = sub.add_parser("all", parents=[common], help="pull, build, and check; does not gzip")
    everything.add_argument("--full-repull", action="store_true", help="ignore complete raw files and re-pull the three-year window")
    return parser, parser.parse_args(argv)


def main(argv: list[str]) -> int:
    parser, args = parse_args(argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if not args.command:
            parser.print_help()
            return 2
        configure(args.work)
        if args.command == "pull":
            return cmd_pull(args.full_repull)
        if args.command == "build":
            return cmd_build()
        if args.command == "check":
            return cmd_check()
        if args.command == "gzip":
            return cmd_gzip()
        if args.command == "all":
            return cmd_all(args.full_repull)
        parser.print_help()
        return 2
    except RefreshError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except AssertionError as exc:
        if args.self_test:
            print(f"self-test failed: {exc}", file=sys.stderr)
            return 1
        traceback.print_exc()
        return 2
    except Exception:
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
