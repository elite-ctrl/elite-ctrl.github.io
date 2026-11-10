#!/usr/bin/env python3
"""Refresh the HKEX board-meeting snapshot embedded in board-meeting-heatmap.html.

Fetches the public Main and GEM Board Meeting Notice pages, maps purpose and
period the way that page already does, and rewrites only:

  - the `const DATA = …;` blob
  - the intro "Snapshot …" date
  - the privacy note "published snapshot dated …"

The meeting set is compared as JSON with sorted keys and a stable row order.
If that payload matches what is already on the page, the file is left untouched
(including the snapshot date). A failed fetch, a bot challenge, an unknown
purpose/period, or an empty list exits before any write so the page cannot be
wiped to zero meetings.

The privacy-note frequency sentence ("It is updated every two weeks around
08:30 (Hong Kong time).") is not a snapshot date. A write that changes it,
or any other copy outside DATA and the two snapshot phrases, is refused.

Local use:
  python3 scripts/refresh-board-meeting-heatmap.py
  python3 scripts/refresh-board-meeting-heatmap.py --dry-run
  python3 scripts/refresh-board-meeting-heatmap.py --self-test

The fortnightly job that calls this script is
.github/workflows/refresh-board-meeting-heatmap.yml
(Tuesday 00:30 UTC = 08:30 Asia/Hong_Kong on even ISO weeks, plus
workflow_dispatch, which always refreshes).
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date
from html import unescape
from pathlib import Path

MAIN_URL = "https://www3.hkexnews.hk/reports/bmn/ebmn_c.htm"
GEM_URL = "https://www3.hkexnews.hk/reports/bmn/cbmngem.htm"

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HTML = ROOT / "board-meeting-heatmap.html"

FIELDS = (
    "date",
    "dateDisplay",
    "name",
    "code",
    "purposeZh",
    "purposeEn",
    "purposeBucket",
    "period",
    "board",
)

MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

# Exact purposeZh → (purposeEn, purposeBucket) pairs taken from the live page.
# purposeBucket must stay inside the page's BUCKETS list or the filter hides the row.
EXACT_PURPOSES = {
    "股息": ("Dividend", "Dividend"),
    "特別股息": ("Special dividend", "Special dividend"),
    "中期業績/股息": ("Interim results / dividend", "Interim results"),
    "中期業績": ("Interim results / dividend", "Interim results"),
    "中期業績/分派": ("Interim results / dividend", "Interim results"),
    "業績/中期股息": ("Interim results / dividend", "Interim results"),
    "業績/股息": ("Interim results / dividend", "Interim results"),
    "業績/分派": ("Interim results / dividend", "Interim results"),
    "第三季業績": ("Q3 results", "Q3 results"),
    "第三季業績/股息": ("Q3 results", "Q3 results"),
    "第三季業績/分派": ("Q3 results", "Q3 results"),
    "季度業績": ("Quarterly results", "Quarterly results"),
    "季度業績/股息": ("Quarterly results", "Quarterly results"),
    "季度業績/分派": ("Quarterly results", "Quarterly results"),
    "業績": ("Results", "Results"),
    "末期業績/股息": ("Final results / dividend", "Final results"),
    "末期業績": ("Final results", "Final results"),
    "末期業績/分派": ("Final results / dividend", "Final results"),
}

FW_DIGITS = str.maketrans("０１２３４５６７８９／", "0123456789/")
CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "兩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

RETRY_DELAYS = (5, 10, 20, 40, 80)
RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}


class RefreshError(Exception):
    """A fetch or parse problem that must not rewrite the page."""


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def fail(message: str) -> None:
    raise RefreshError(message)


def clean_text(value: str) -> str:
    text = unescape(value)
    text = (
        text.replace("\xa0", " ")
        .replace("\u3000", " ")
        .replace("\r", "")
        .replace("\n", "")
    )
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text


def parse_cn_count(token: str) -> int:
    if token.isdigit():
        return int(token)
    if not token or any(ch not in CN_DIGITS and ch != "十" for ch in token):
        raise ValueError(token)
    if token == "十":
        return 10
    if token.startswith("十"):
        rest = token[1:]
        return 10 + (CN_DIGITS[rest] if rest else 0)
    if "十" in token:
        high, low = token.split("十", 1)
        return CN_DIGITS[high] * 10 + (CN_DIGITS[low] if low else 0)
    if len(token) == 1:
        return CN_DIGITS[token]
    raise ValueError(token)


def parse_dmy(value: str, year_digits: int) -> tuple[int, int, int]:
    match = re.fullmatch(rf"(\d{{1,2}})/(\d{{1,2}})/(\d{{{year_digits}}})", value)
    if not match:
        fail(f"unrecognized date {value!r}")
    day, month, year = (int(part) for part in match.groups())
    if year_digits == 2:
        year += 2000
    try:
        date(year, month, day)
    except ValueError:
        fail(f"invalid date {value!r}")
    return year, month, day


def iso_from_dmy(value: str) -> str:
    year, month, day = parse_dmy(value, 4)
    return f"{year:04d}-{month:02d}-{day:02d}"


def display_from_dmy(value: str) -> str:
    year, month, day = parse_dmy(value, 4)
    return f"{day:02d}/{month:02d}/{year:04d}"


def long_from_iso(iso: str) -> str:
    year, month, day = (int(part) for part in iso.split("-"))
    date(year, month, day)
    return f"{day} {MONTHS[month - 1]} {year}"


def norm_code(raw: str) -> str:
    code = clean_text(raw).replace(" ", "")
    if not re.fullmatch(r"\d{1,6}", code):
        fail(f"unexpected stock code {raw!r}")
    code = code.lstrip("0") or "0"
    return code


def map_purpose(purpose_zh: str) -> tuple[str, str]:
    """Return (purposeEn, purposeBucket) in the live page's style."""
    key = purpose_zh.strip().replace("／", "/").replace(" ", "")
    if key in EXACT_PURPOSES:
        return EXACT_PURPOSES[key]

    has_dividend = ("股息" in key) or ("分派" in key)
    has_results = "業績" in key

    if not has_results:
        if "特別" in key and "股息" in key:
            return ("Special dividend", "Special dividend")
        if "股息" in key or "分派" in key:
            return ("Dividend", "Dividend")
        fail(f"unknown purpose {purpose_zh!r}")

    # Quarter phrases keep the short English label already used for Q3 /
    # quarterly rows (the trailing dividend is not repeated in purposeEn).
    if "第三季" in key:
        return ("Q3 results", "Q3 results")
    if "第一季" in key or "首季" in key:
        return ("Q1 results", "Quarterly results")
    if "第二季" in key:
        return ("Q2 results", "Quarterly results")
    if "第四季" in key:
        return ("Q4 results", "Quarterly results")
    if "季度" in key:
        return ("Quarterly results", "Quarterly results")
    if "末期" in key or "全年" in key or "年度" in key:
        if has_dividend:
            return ("Final results / dividend", "Final results")
        return ("Final results", "Final results")
    if "中期" in key or key in {"業績/股息", "業績/分派"}:
        return ("Interim results / dividend", "Interim results")
    if key == "業績" or key.startswith("業績"):
        return ("Results", "Results")
    fail(f"unknown purpose {purpose_zh!r}")


def map_period(period_zh: str) -> str:
    """Map a Chinese BMN period to the English form already on the page."""
    raw = clean_text(period_zh)
    if not raw:
        return ""
    text = raw.translate(FW_DIGITS).replace(" ", "")

    match = re.fullmatch(
        r"截至(\d{2}/\d{2}/\d{2})止(\d+|[零〇一二三四五六七八九十兩]+)個月",
        text,
    )
    if match:
        count = parse_cn_count(match.group(2))
        if not 1 <= count <= 24:
            fail(f"unexpected period length in {period_zh!r}")
        day, month, year = (int(part) for part in match.group(1).split("/"))
        try:
            date(2000 + year, month, day)
        except ValueError:
            fail(f"invalid period date in {period_zh!r}")
        shown = f"{day:02d}/{month:02d}/{year:02d}"
        unit = "month" if count == 1 else "months"
        return f"{count} {unit} ended {shown}"

    match = re.fullmatch(r"截至(\d{2}/\d{2}/\d{2})止季度", text)
    if match:
        return f"Quarter ended {match.group(1)}"

    match = re.fullmatch(r"截至(\d{2}/\d{2}/\d{2})期間", text)
    if match:
        return f"Period ended {match.group(1)}"

    match = re.fullmatch(r"(?:截至(\d{2}/\d{2}/\d{2})止年度|年度(\d{2}/\d{2}/\d{2}))", text)
    if match:
        shown = match.group(1) or match.group(2)
        return f"Year ended {shown}"

    fail(f"unknown period {period_zh!r}")


def page_ok(text: str) -> bool:
    if "董事會會議" not in text or "會議日期" not in text:
        return False
    lowered = text.lower()
    if "</table>" not in lowered and "</html>" not in lowered:
        return False
    return True


def parse_list_date(html: str, board: str) -> str:
    match = re.search(r"日期\s*[:：]\s*(\d{1,2}/\d{1,2}/\d{4})", html)
    if not match:
        fail(f"{board}: HKEX list date (日期) not found")
    return iso_from_dmy(display_from_dmy(match.group(1)))


def parse_meetings(html: str, board: str) -> list[dict]:
    if not page_ok(html):
        fail(f"{board}: response is not a Board Meeting Notice page")
    meetings = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, flags=re.I | re.S):
        cells = re.findall(r"<font\b[^>]*>(.*?)</font>", tr, flags=re.I | re.S)
        if not cells:
            continue
        first = clean_text(cells[0])
        if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", first):
            continue
        if len(cells) != 6:
            fail(f"{board}: meeting row {first} has {len(cells)} cells, expected 6")
        date_s, _spacer, name, code, purpose, period = (clean_text(cell) for cell in cells)
        if not name:
            fail(f"{board}: missing company name on {date_s}")
        purpose_en, purpose_bucket = map_purpose(purpose)
        meetings.append(
            {
                "date": iso_from_dmy(date_s),
                "dateDisplay": display_from_dmy(date_s),
                "name": name,
                "code": norm_code(code),
                "purposeZh": purpose,
                "purposeEn": purpose_en,
                "purposeBucket": purpose_bucket,
                "period": map_period(period),
                "board": board,
            }
        )

    markers = re.findall(
        r"<font\b[^>]*>\s*(\d{2}/\d{2}/\d{4})\s*</font>",
        html,
        flags=re.I,
    )
    if len(markers) != len(meetings):
        fail(
            f"{board}: saw {len(markers)} dated cells but parsed {len(meetings)} rows; "
            "refusing a partial table"
        )
    return meetings


def data_span(html: str) -> tuple[int, int, dict]:
    marker = "const DATA = "
    start = html.find(marker)
    if start < 0:
        fail("const DATA assignment not found")
    if html.find(marker, start + len(marker)) != -1:
        fail("multiple const DATA assignments")
    json_start = start + len(marker)
    try:
        payload, end = json.JSONDecoder().raw_decode(html, json_start)
    except json.JSONDecodeError as exc:
        fail(f"existing DATA is not valid JSON ({exc})")
    if not isinstance(payload, dict):
        fail("existing DATA is not an object")
    if html[end:end + 1] != ";":
        fail("DATA assignment is not terminated by ';'")
    return start, end + 1, payload


def load_existing(html: str) -> list[dict]:
    _, _, payload = data_span(html)
    meetings = payload.get("meetings")
    if not isinstance(meetings, list) or not meetings:
        fail("existing DATA.meetings is empty; refusing to continue from a blank page")
    normalized = []
    for index, meeting in enumerate(meetings):
        if not isinstance(meeting, dict):
            fail(f"existing meeting {index} is not an object")
        row = {}
        for field in FIELDS:
            value = meeting.get(field)
            if not isinstance(value, str):
                fail(f"existing meeting {index} is missing string field {field}")
            row[field] = value
        normalized.append(row)
    return normalized


def load_buckets(html: str) -> list[str]:
    match = re.search(r"const BUCKETS = (\[.*?\]);", html, flags=re.S)
    if not match:
        fail("BUCKETS array not found")
    try:
        buckets = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        fail(f"BUCKETS array is not JSON ({exc})")
    if not isinstance(buckets, list) or not buckets or not all(isinstance(item, str) for item in buckets):
        fail("BUCKETS array is empty or invalid")
    return buckets


def canonical(meetings: list[dict]) -> str:
    rows = [{field: meeting[field] for field in FIELDS} for meeting in meetings]
    rows.sort(key=lambda meeting: tuple(meeting[field] for field in FIELDS))
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def mask_volatile(html: str) -> str:
    start, end, _ = data_span(html)
    masked = html[:start] + "const DATA = {};" + html[end:]
    masked = re.sub(r"Snapshot \d{1,2} [A-Z][a-z]+ \d{4}", "Snapshot MASK", masked)
    masked = re.sub(
        r"published snapshot dated \d{1,2} [A-Z][a-z]+ \d{4}",
        "published snapshot dated MASK",
        masked,
    )
    return masked


def replace_snapshot_copy(html: str, long_date: str) -> str:
    replacements = (
        (re.compile(r"Snapshot \d{1,2} [A-Z][a-z]+ \d{4}"), f"Snapshot {long_date}"),
        (
            re.compile(r"published snapshot dated \d{1,2} [A-Z][a-z]+ \d{4}"),
            f"published snapshot dated {long_date}",
        ),
    )
    for pattern, replacement in replacements:
        found = pattern.findall(html)
        if len(found) != 1:
            fail(f"expected exactly one snapshot phrase ({pattern.pattern}), found {len(found)}")
        html = pattern.sub(replacement, html, count=1)
    return html


def build_html(html: str, meetings: list[dict], snapshot_iso: str) -> str:
    buckets = load_buckets(html)
    unknown = sorted({row["purposeBucket"] for row in meetings if row["purposeBucket"] not in buckets})
    if unknown:
        fail(
            "purposeBucket values are not in the page BUCKETS list, so filters would hide them: "
            + ", ".join(unknown)
        )
    if not meetings:
        fail("refusing to write an empty meeting list")

    payload = {
        "sourceDate": snapshot_iso,
        "sources": {"Main": MAIN_URL, "GEM": GEM_URL},
        "meetings": [{field: row[field] for field in FIELDS} for row in meetings],
    }
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    start, end, _ = data_span(html)
    updated = html[:start] + "const DATA = " + blob + ";" + html[end:]
    updated = replace_snapshot_copy(updated, long_from_iso(snapshot_iso))

    if mask_volatile(html) != mask_volatile(updated):
        fail("refresh would change more than DATA and the snapshot dates; not writing")

    _, _, written = data_span(updated)
    if written.get("sourceDate") != snapshot_iso:
        fail("rewritten DATA did not keep the snapshot date")
    if canonical(written["meetings"]) != canonical(meetings):
        fail("rewritten DATA meetings did not round-trip")
    if "Snapshot " + long_from_iso(snapshot_iso) not in updated:
        fail("intro snapshot date was not updated")
    if "published snapshot dated " + long_from_iso(snapshot_iso) not in updated:
        fail("privacy-note snapshot date was not updated")
    return updated


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".bmn-tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def choose_snapshot(*iso_dates: str) -> str:
    parsed = []
    for iso in iso_dates:
        year, month, day = (int(part) for part in iso.split("-"))
        parsed.append(date(year, month, day))
    if abs((parsed[0] - parsed[1]).days) > 7:
        fail(
            "Main list date "
            f"{iso_dates[0]} and GEM list date {iso_dates[1]} differ by more than 7 days"
        )
    return max(iso_dates)


def fetch(url: str, opener: urllib.request.OpenerDirector) -> str:
    """GET a public HKEX page, retrying Akamai/HTTP failures with backoff."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-HK,zh-TW;q=0.9,zh;q=0.8,en;q=0.5",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://www.hkexnews.hk/",
        },
    )
    attempts = len(RETRY_DELAYS) + 1
    last_error = "no response"
    for attempt in range(attempts):
        try:
            with opener.open(request, timeout=60) as response:
                status = getattr(response, "status", 200)
                body = response.read()
            text = body.decode("utf-8", errors="replace")
            if status == 200 and page_ok(text):
                log(f"fetched {url} ({len(body)} bytes)")
                return text
            last_error = f"HTTP {status}, usable={page_ok(text)}, bytes={len(body)}"
            retry = status in RETRY_STATUSES or not page_ok(text)
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            retry = exc.code in RETRY_STATUSES or exc.code in {403, 401}
            if exc.code in {400, 404, 410}:
                fail(f"fetch {url} failed: {last_error}")
        except Exception as exc:  # noqa: BLE001 — network errors must retry, then fail closed
            last_error = f"{type(exc).__name__}: {exc}"
            retry = True

        if attempt >= len(RETRY_DELAYS) or not retry:
            break
        delay = RETRY_DELAYS[attempt]
        log(f"retry {attempt + 1} for {url} in {delay}s ({last_error})")
        time.sleep(delay)

    fail(f"fetch failed for {url}: {last_error}. Page left unchanged.")


def load_board(board: str, url: str, override: str | None, opener) -> str:
    if override:
        path = Path(override)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            fail(f"{board}: cannot read {path} ({exc})")
        if not page_ok(text):
            fail(f"{board}: saved page {path} is not a usable BMN document")
        log(f"loaded {board} fixture {path}")
        return text
    return fetch(url, opener)


def result_line(changed: bool, snapshot: str, meetings: int, previous: int) -> str:
    flag = "yes" if changed else "no"
    return (
        f"RESULT changed={flag} snapshot={snapshot} "
        f"meetings={meetings} previous={previous}"
    )


def refresh(html_path: Path, main_html: str | None, gem_html: str | None, dry_run: bool) -> str:
    original = html_path.read_text(encoding="utf-8")
    existing = load_existing(original)
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    main_page = load_board("Main", MAIN_URL, main_html, opener)
    gem_page = load_board("GEM", GEM_URL, gem_html, opener)
    main_rows = parse_meetings(main_page, "Main")
    gem_rows = parse_meetings(gem_page, "GEM")
    meetings = main_rows + gem_rows
    if not meetings:
        fail("parsed zero meetings from Main and GEM; refusing to wipe the page")
    if not main_rows:
        fail("parsed zero Main Board meetings; refusing a partial snapshot")

    main_date = parse_list_date(main_page, "Main")
    gem_date = parse_list_date(gem_page, "GEM")
    snapshot = choose_snapshot(main_date, gem_date)
    if main_date != gem_date:
        log(f"Main and GEM list dates differ; snapshot date is the later one ({snapshot})")
    log(
        f"main_rows={len(main_rows)} gem_rows={len(gem_rows)} "
        f"list_date_main={main_date} list_date_gem={gem_date} snapshot={snapshot}"
    )

    changed = canonical(existing) != canonical(meetings)
    if not changed:
        line = result_line(False, snapshot, len(meetings), len(existing))
        print(line, flush=True)
        log("meeting set unchanged; page not modified")
        return line

    updated = build_html(original, meetings, snapshot)
    if dry_run:
        line = result_line(True, snapshot, len(meetings), len(existing))
        print(line, flush=True)
        log("dry-run: meeting set changed; page not written")
        return line

    atomic_write(html_path, updated)
    written = html_path.read_text(encoding="utf-8")
    if written != updated:
        fail("written page did not match the prepared snapshot")
    if not load_existing(written):
        fail("written page has no meetings")
    line = result_line(True, snapshot, len(meetings), len(existing))
    print(line, flush=True)
    log(f"updated {html_path} ({len(existing)} → {len(meetings)} meetings)")
    return line


def _sample_page(list_date: str, rows: list[tuple[str, str, str, str, str]]) -> str:
    trs = []
    for meeting_date, name, code, purpose, period in rows:
        trs.append(
            "<tr>"
            f"<td width=75><font face='monospace'>{meeting_date}</font></td>"
            "<td width=30><font face='monospace'></font></td>"
            f"<td width=120><font face='monospace'>{name}</font></td>"
            f"<td width=50><font face='monospace'>&nbsp;{code}</font></td>"
            f"<td width=140><font face='monospace'>{purpose}</font></td>"
            f"<td><font face='monospace'>{period}</font></td>"
            "</tr>"
        )
    body = "".join(trs)
    return (
        "<html><head><title>Hong Kong Exchanges and Clearing Limited</title></head><body>"
        "<span>董事會會議通知</span>"
        f"<font class=textfont>日期 : {list_date}<br/>會議日期 column follows</font>"
        "<table class=textfont><tr><td><font>會議日期</font></td>"
        "<td><font></font></td><td><font>證券簡稱</font></td>"
        "<td><font>代號</font></td><td><font>目的</font></td>"
        "<td><font>期間</font></td></tr>"
        f"{body}</table></body></html>"
    )


def _sample_heatmap(meetings: list[dict], long_date: str) -> str:
    payload = {
        "sourceDate": "2026-11-06",
        "sources": {"Main": MAIN_URL, "GEM": GEM_URL},
        "meetings": meetings,
    }
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    buckets = [
        "Interim results",
        "Q3 results",
        "Results",
        "Quarterly results",
        "Special dividend",
        "Final results",
        "Dividend",
    ]
    return (
        "<p>same Tools family as Call the Ledger. "
        f"Snapshot {long_date}.</p>\n"
        "<p>Stock code watchlist</p>\n"
        "<p>Call the Gaps stays put. "
        f"This page shows a published snapshot dated {long_date}. "
        "It is updated every two weeks around 08:30 (Hong Kong time).</p>\n"
        "<script>\n"
        f"const DATA = {blob};\n"
        "const BUCKETS = "
        + json.dumps(buckets, ensure_ascii=False)
        + ";\n"
        "</script>\n"
    )


def self_test() -> None:
    assert map_period("") == ""
    assert map_period("截至30/09/26止9個月") == "9 months ended 30/09/26"
    assert map_period("截至30/09/26止6個月") == "6 months ended 30/09/26"
    assert map_period("截至30/09/26止3個月") == "3 months ended 30/09/26"
    assert map_period("截至30/09/26止九個月") == "9 months ended 30/09/26"
    assert map_period("截至30/09/26止季度") == "Quarter ended 30/09/26"
    assert map_period("截至30/09/26期間") == "Period ended 30/09/26"
    assert map_period("年度30/06/26") == "Year ended 30/06/26"
    assert map_period("截至30/06/26止年度") == "Year ended 30/06/26"
    assert map_period("截至31/12/25止十二個月") == "12 months ended 31/12/25"
    assert map_period("截至31/03/26止1個月") == "1 month ended 31/03/26"
    assert map_period("截至３０／０９／２６止９個月") == "9 months ended 30/09/26"
    try:
        map_period("不適用")
    except RefreshError:
        pass
    else:
        raise AssertionError("unknown period should fail")

    expected = {
        "股息": ("Dividend", "Dividend"),
        "特別股息": ("Special dividend", "Special dividend"),
        "中期業績/股息": ("Interim results / dividend", "Interim results"),
        "中期業績": ("Interim results / dividend", "Interim results"),
        "中期業績/分派": ("Interim results / dividend", "Interim results"),
        "業績/中期股息": ("Interim results / dividend", "Interim results"),
        "業績/股息": ("Interim results / dividend", "Interim results"),
        "第三季業績": ("Q3 results", "Q3 results"),
        "第三季業績/股息": ("Q3 results", "Q3 results"),
        "季度業績": ("Quarterly results", "Quarterly results"),
        "季度業績/股息": ("Quarterly results", "Quarterly results"),
        "業績": ("Results", "Results"),
        "末期業績/股息": ("Final results / dividend", "Final results"),
        "第一季業績": ("Q1 results", "Quarterly results"),
        "第四季業績/股息": ("Q4 results", "Quarterly results"),
        "全年業績/股息": ("Final results / dividend", "Final results"),
    }
    for purpose, pair in expected.items():
        assert map_purpose(purpose) == pair, purpose
    try:
        map_purpose("其他事項")
    except RefreshError:
        pass
    else:
        raise AssertionError("unknown purpose should fail")

    assert norm_code("\xa0\xa00486") == "486"
    assert norm_code("89888") == "89888"

    base_rows = [
        ("09/11/2026", "俄鋁", "0486", "股息", ""),
        ("10/11/2026", "ＴＣＬ電子", "1070", "季度業績", "截至30/09/26止9個月"),
    ]
    meetings = parse_meetings(_sample_page("06/11/2026", base_rows), "Main")
    assert meetings[0]["code"] == "486"
    assert meetings[0]["period"] == ""
    assert meetings[0]["name"] == "俄鋁"
    assert meetings[1]["name"] == "ＴＣＬ電子"
    assert meetings[1]["period"] == "9 months ended 30/09/26"
    assert meetings[1]["purposeEn"] == "Quarterly results"

    heatmap_meetings = []
    for row in meetings:
        copied = dict(row)
        heatmap_meetings.append(copied)
    # One GEM row so a Main+GEM fixture matches the embedded list.
    gem_only = parse_meetings(
        _sample_page("06/11/2026", [("09/11/2026", "海王英特龍", "8329", "特別股息", "")]),
        "GEM",
    )
    page = _sample_heatmap(heatmap_meetings + gem_only, "6 November 2026")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        html_path = root / "board-meeting-heatmap.html"
        main_path = root / "main.htm"
        gem_path = root / "gem.htm"
        html_path.write_text(page, encoding="utf-8")
        main_path.write_text(_sample_page("10/11/2026", base_rows), encoding="utf-8")
        gem_path.write_text(
            _sample_page("10/11/2026", [("09/11/2026", "海王英特龍", "8329", "特別股息", "")]),
            encoding="utf-8",
        )
        before = html_path.read_text(encoding="utf-8")
        line = refresh(html_path, str(main_path), str(gem_path), dry_run=False)
        assert "changed=no" in line
        assert html_path.read_text(encoding="utf-8") == before

        main_path.write_text(
            _sample_page(
                "11/11/2026",
                base_rows + [("12/11/2026", "新公司", "1", "末期業績/股息", "年度30/06/26")],
            ),
            encoding="utf-8",
        )
        line = refresh(html_path, str(main_path), str(gem_path), dry_run=True)
        assert "changed=yes" in line
        assert "snapshot=2026-11-11" in line
        assert html_path.read_text(encoding="utf-8") == before

        line = refresh(html_path, str(main_path), str(gem_path), dry_run=False)
        assert "changed=yes" in line
        updated = html_path.read_text(encoding="utf-8")
        assert "Snapshot 11 November 2026." in updated
        assert "published snapshot dated 11 November 2026." in updated
        assert updated.count("It is updated every two weeks around 08:30 (Hong Kong time).") == 1
        assert "Call the Ledger" in updated
        assert "Call the Gaps" in updated
        assert "Stock code watchlist" in updated
        assert "新公司" in updated
        assert "Year ended 30/06/26" in updated
        assert "const BUCKETS = " in updated
        payload = data_span(updated)[2]
        assert payload["sourceDate"] == "2026-11-11"
        assert len(payload["meetings"]) == 4

        # Empty and challenge pages must fail without a further write.
        sealed = html_path.read_text(encoding="utf-8")
        main_path.write_text(_sample_page("12/11/2026", []), encoding="utf-8")
        try:
            refresh(html_path, str(main_path), str(gem_path), dry_run=False)
        except RefreshError as exc:
            assert "zero Main" in str(exc)
        else:
            raise AssertionError("empty Main list should fail")
        assert html_path.read_text(encoding="utf-8") == sealed

        main_path.write_text(
            "<html><title>Access Denied</title><p>Reference #18.errors.edgesuite.net</p></html>",
            encoding="utf-8",
        )
        try:
            refresh(html_path, str(main_path), str(gem_path), dry_run=False)
        except RefreshError as exc:
            assert "not a usable BMN" in str(exc)
        else:
            raise AssertionError("challenge page should fail")
        assert html_path.read_text(encoding="utf-8") == sealed

        main_path.write_text(
            _sample_page("11/11/2026", [("01/12/2026", "謎", "9", "其他事項", "")]),
            encoding="utf-8",
        )
        try:
            refresh(html_path, str(main_path), str(gem_path), dry_run=False)
        except RefreshError as exc:
            assert "unknown purpose" in str(exc)
        else:
            raise AssertionError("unknown purpose should fail")
        assert html_path.read_text(encoding="utf-8") == sealed

    # The live page's frequency sentence must survive a snapshot-date rewrite.
    # build_html is in memory only; this must not touch the published file.
    frequency = "It is updated every two weeks around 08:30 (Hong Kong time)."
    live_path = DEFAULT_HTML
    live = live_path.read_text(encoding="utf-8")
    if live.count(frequency) != 1:
        raise AssertionError("frequency sentence must appear once on the live page")
    patched = build_html(live, load_existing(live), "2030-01-08")
    if patched.count(frequency) != 1:
        raise AssertionError("refresh dropped the frequency sentence")
    if "Snapshot 8 January 2030" not in patched:
        raise AssertionError("intro snapshot date was not rewritten in memory")
    if "published snapshot dated 8 January 2030" not in patched:
        raise AssertionError("privacy-note snapshot date was not rewritten in memory")
    if live_path.read_text(encoding="utf-8") != live:
        raise AssertionError("self-test wrote the live page")

    log("self-test ok")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_HTML,
        help="heatmap page to update (default: board-meeting-heatmap.html)",
    )
    parser.add_argument("--main-html", help="read the Main Board page from a file instead of HKEX")
    parser.add_argument("--gem-html", help="read the GEM page from a file instead of HKEX")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and report RESULT, but do not write the page",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run built-in parser checks and exit",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        if args.self_test:
            self_test()
            return 0
        refresh(args.file, args.main_html, args.gem_html, args.dry_run)
        return 0
    except RefreshError as exc:
        log(f"error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
