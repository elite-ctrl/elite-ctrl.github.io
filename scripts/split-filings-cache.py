#!/usr/bin/env python3
"""Split the whole-market filings gzip into one JSON file per issuer.

The bilingual filings page loads stocks.json, tiers.json, and filings-meta.json
first, then fetches one issuer file after a name is chosen. It does not read
filings-cache.json.gz.

Writes, next to this repo:
  filings-meta.json          cache header (snapshot, source, exclusions)
  data/filings/{code}.json   one issuer, compact UTF-8 JSON

A later refresh should produce a new filings-cache.json.gz and run this script
before commit. Commit filings-meta.json and data/filings/. Do not commit the
gzip: git cannot diff it, and the page no longer fetches it.

Unchanged issuer files are left untouched, so a refresh only shows issuers
whose filings changed. Issuer files that disappeared from the cache are deleted.

  python3 scripts/split-filings-cache.py
  python3 scripts/split-filings-cache.py --input /path/to/filings-cache.json.gz
  python3 scripts/split-filings-cache.py --dry-run
  python3 scripts/split-filings-cache.py --self-test
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE_DIGITS = 5


def repo_html_ok() -> None:
    html = (ROOT / "bilingual-hkex-filings.html").read_text(encoding="utf-8")
    if "filings-cache.json.gz" in html:
        raise SystemExit("bilingual-hkex-filings.html still fetches filings-cache.json.gz")
    for needle in ("filings-meta.json", "data/filings/", "titlesearch.xhtml"):
        if needle not in html:
            raise SystemExit("bilingual-hkex-filings.html is missing " + needle)


def load_cache(path: Path) -> dict:
    try:
        raw = gzip.decompress(path.read_bytes())
    except OSError as err:
        raise SystemExit(f"could not read {path}: {err}") from err
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as err:
        raise SystemExit(f"{path} is not a JSON gzip: {err}") from err
    if not isinstance(payload, dict) or not isinstance(payload.get("issuers"), dict):
        raise SystemExit(f"{path} has no issuers object")
    return payload


def issuer_bytes(pack: dict) -> bytes:
    return (json.dumps(pack, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def meta_bytes(payload: dict) -> bytes:
    meta = {key: value for key, value in payload.items() if key != "issuers"}
    meta["issuerCount"] = len(payload["issuers"])
    text = json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def split(cache_path: Path, root: Path, dry_run: bool) -> dict:
    payload = load_cache(cache_path)
    issuers = payload["issuers"]
    filings_dir = root / "data" / "filings"
    meta_path = root / "filings-meta.json"
    written = 0
    unchanged = 0
    removed = 0
    expected: set[str] = set()

    for code, pack in issuers.items():
        if not isinstance(code, str) or len(code) != CODE_DIGITS or not code.isdigit():
            raise SystemExit(f"refusing issuer code {code!r}")
        if not isinstance(pack, dict):
            raise SystemExit(f"issuer {code} is not an object")
        expected.add(code)
        body = issuer_bytes(pack)
        dest = filings_dir / f"{code}.json"
        if dest.is_file() and dest.read_bytes() == body:
            unchanged += 1
            continue
        written += 1
        if dry_run:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)

    if filings_dir.is_dir():
        for path in filings_dir.glob("*.json"):
            if path.stem not in expected:
                removed += 1
                if not dry_run:
                    path.unlink()

    meta_body = meta_bytes(payload)
    meta_changed = not meta_path.is_file() or meta_path.read_bytes() != meta_body
    if meta_changed and not dry_run:
        meta_path.write_bytes(meta_body)

    return {
        "issuers": len(expected),
        "written": written,
        "unchanged": unchanged,
        "removed": removed,
        "meta_changed": meta_changed,
        "dry_run": dry_run,
    }


def report(stats: dict) -> None:
    action = "would write" if stats["dry_run"] else "wrote"
    print(
        f"{action} {stats['written']} issuer files, "
        f"{stats['unchanged']} unchanged, {stats['removed']} removed, "
        f"meta_changed={str(stats['meta_changed']).lower()}, issuers={stats['issuers']}"
    )


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = {
            "snapshot": "11 November 2026 (Asia/Hong_Kong)",
            "note": "fixture",
            "issuers": {
                "00001": {"code": "00001", "stockId": 1, "nameEn": "CKH", "filings": [{"titleEn": "A"}]},
                "00700": {"code": "00700", "stockId": 7609, "nameEn": "TENCENT", "filings": [{"titleEn": "B"}]},
            },
        }
        gzip_path = root / "filings-cache.json.gz"
        gzip_path.write_bytes(gzip.compress(json.dumps(payload).encode("utf-8")))

        dry = split(gzip_path, root, dry_run=True)
        if dry["written"] != 2 or (root / "data" / "filings").exists() or (root / "filings-meta.json").exists():
            raise SystemExit("dry-run wrote files")

        first = split(gzip_path, root, dry_run=False)
        if first["written"] != 2 or first["unchanged"] != 0 or first["removed"] != 0:
            raise SystemExit(f"first split stats {first}")
        meta = json.loads((root / "filings-meta.json").read_text(encoding="utf-8"))
        if "issuers" in meta or meta.get("issuerCount") != 2 or meta.get("snapshot") != payload["snapshot"]:
            raise SystemExit(f"bad meta {meta}")
        one = json.loads((root / "data" / "filings" / "00001.json").read_text(encoding="utf-8"))
        if one.get("nameEn") != "CKH" or one.get("filings") != [{"titleEn": "A"}]:
            raise SystemExit(f"bad issuer file {one}")

        second = split(gzip_path, root, dry_run=False)
        if second["written"] != 0 or second["unchanged"] != 2 or second["meta_changed"]:
            raise SystemExit(f"second split should be a no-op {second}")

        payload["issuers"].pop("00700")
        payload["issuers"]["00001"]["filings"].append({"titleEn": "C"})
        gzip_path.write_bytes(gzip.compress(json.dumps(payload).encode("utf-8")))
        third = split(gzip_path, root, dry_run=False)
        if third["written"] != 1 or third["unchanged"] != 0 or third["removed"] != 1:
            raise SystemExit(f"third split stats {third}")
        if (root / "data" / "filings" / "00700.json").exists():
            raise SystemExit("removed issuer file still on disk")
        updated = json.loads((root / "data" / "filings" / "00001.json").read_text(encoding="utf-8"))
        if len(updated["filings"]) != 2:
            raise SystemExit("updated issuer did not replace the file")

        try:
            bad = dict(payload)
            bad["issuers"] = {"../x": {}}
            bad_path = root / "bad.json.gz"
            bad_path.write_bytes(gzip.compress(json.dumps(bad).encode("utf-8")))
            split(bad_path, root, dry_run=True)
        except SystemExit as err:
            if "refusing issuer code" not in str(err):
                raise
        else:
            raise SystemExit("bad issuer code was accepted")

    repo_html_ok()
    print("self-test ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "filings-cache.json.gz")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.input.is_file():
        raise SystemExit(f"missing cache gzip: {args.input}")
    report(split(args.input, args.root, args.dry_run))


if __name__ == "__main__":
    main()
