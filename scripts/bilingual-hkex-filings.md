# Bilingual HKEXnews filings refresh

Studio command for the cache behind `bilingual-hkex-filings.html`. The page reads a published snapshot. It does not call HKEXnews. This script is the offline refresh. It writes only inside its work directory. It does not write the Live `cache-meta.json`, `stocks.json`, `tiers.json`, or `filings/{prefix}/{code}.json.gz` files, and it does not download PDF bodies.

The Wednesday and Sunday run, around 08:30 Asia/Hong_Kong, is the Grok Bot routine on the studio computer. Do not add a GitHub Actions cron that pulls HKEXnews.

## What the page reads

On arrival the page loads `cache-meta.json`, `stocks.json`, and `tiers.json`. After a code or name is chosen, or a `#/issuer/XXXXX` route is opened, it fetches one issuer file:

```text
filings/{prefix}/{code}.json.gz
```

`prefix` is the first two digits of the five-digit stock code. `00001` is `filings/00/00001.json.gz`. `03759` is `filings/03/03759.json.gz`. Take the code from the filename by stripping the full `.json.gz` suffix. `Path.stem` of `03759.json.gz` is `03759.json`, and that leftover is wrong.

`filings-cache.json` and `filings-cache.json.gz` are not part of this layout. The published site no longer serves the monolith.

## Commands

Work files go to `data/hkex-filings-work/` (gitignored), or to `--work`, or to `HKEX_FILINGS_ROOT`. Do not point that directory at the repository root, or at the Live `filings/` tree.

```bash
python3 scripts/refresh-bilingual-hkex-filings.py --self-test
python3 scripts/refresh-bilingual-hkex-filings.py pull --work DIR
python3 scripts/refresh-bilingual-hkex-filings.py build --work DIR
python3 scripts/refresh-bilingual-hkex-filings.py check --work DIR
```

`all` is pull, then build, then check.

```bash
python3 scripts/refresh-bilingual-hkex-filings.py all --work DIR
```

`build` writes, inside the work directory only:

- `cache-meta.json`
- `stocks.json`
- `tiers.json`
- `filings/{prefix}/{code}.json.gz` for every issuer with `hasCache` true

Each issuer file is gzip-9 JSON. The compact payload is `code`, `stockId`, `nameEn`, `nameTc`, `snapshot`, `sourceWindow`, `stats`, and `filings`. Filing rows use `dateTime`, `newsIdEn`, `newsIdTc`, `titleEn`, `titleTc`, `tier1Code`, `tier1En`, `tier1Tc`, `tier2En`, `tier2Tc`, `categoryEn`, `categoryTc`, `pdfEn`, `pdfTc`, `fileInfoEn`, and `fileInfoTc`. Every issuer file carries the same `snapshot` string as `cache-meta.json`. The page notes snapshot drift when they differ.

A later Wednesday or Sunday run rewrites an issuer file only when that compact payload changed, leaves unchanged gzip files in place, and deletes orphan issuer files whose codes are no longer `hasCache`. The first run into an empty `filings/` tree writes every issuer file. `cache-meta.json`, `stocks.json`, and `tiers.json` are updated on each build.

`build` does not write `filings-cache.json` or `filings-cache.json.gz`. If a previous run left either file in the work directory, the new write path deletes it.

`check` exits 1 when the build is not shippable: a pull failed, the Main+GEM equity universe is empty, issuer or pair counts sit outside ±20% of the 11 November 2026 Live split snapshot (3,072 issuers, 273,418 pairs, after the Debt and Structured Products strip), `tiers.json` still contains debt or structured-product chips, a `hasCache` flag has no remaining pairs, or the split layout itself is wrong (missing cache-meta keys, a missing or extra issuer file, snapshot drift, or a monolith left behind).

The older 10 November band of 3,072 issuers and 273,587 pairs was the pre-split monolith. Do not use it for this layout.

## Lookback and the monthly full re-pull

An incremental pull reuses monthly raw files outside the lookback. It always re-pulls the last 14 calendar days in Asia/Hong_Kong, including today, even when those days sit inside a monthly file already marked complete. Headline revisions in that window replace the cached row.

That lookback does not repair an older rewrite. About once a month, re-pull the whole three-year window on the studio computer:

```bash
python3 scripts/refresh-bilingual-hkex-filings.py pull --full-repull --work DIR
python3 scripts/refresh-bilingual-hkex-filings.py build --work DIR
python3 scripts/refresh-bilingual-hkex-filings.py check --work DIR
```

The window is today minus three years in Asia/Hong_Kong. 29 February falls back to 28 February. Disk language C is Traditional Chinese and is requested as `lang=zh`. English is `lang=E`.

## Ship prep

`gzip` is the ship-prep confirmation. It runs only after the quality gate would pass. Issuer files are already gzip-9 from `build`, so this step does not compress a monolith. It deletes any leftover `filings-cache.json` or `filings-cache.json.gz` in the work directory, rewrites an issuer file only when its payload changed, and does not write a Live site file.

```bash
python3 scripts/refresh-bilingual-hkex-filings.py gzip --work DIR
```

Copying `cache-meta.json`, `stocks.json`, `tiers.json`, and `filings/` onto the site is a later pull request. This refresh does not publish a cache.

## Cookies

If the studio keeps a Netscape `cookies.txt`, put it at `data/_local/cookies.txt` inside the work directory. The script reads it and never writes it. Do not commit it.

## What the build strips

Contains match, including a cancelled or reissued prefix, not an exact or startswith match:

- Monthly Returns, the whole Tier 1, including 月報表 and 51500
- Next Day Disclosure share buybacks (other NDRs stay, including the standard form title "changes in issued share capital and/or share buybacks" / 已發行股本及/或股份購回; AGM repurchase circulars stay)
- Warrants, options, and 牛熊證 (CBBCs)
- Debt and Structured Products (債券及結構性產品), code 70000, and documents-on-display types 57000, 58000, and 59000

Those debt chips are removed from `tiers.json` as well as from filing rows. `tiers.json` is not a straight copy of the official list: drop 70000, 57000, 58000, 59000, and any chip whose English or Chinese name contains Debt and Structured Products or 債券及結構性產品.

An issuer with no paired filings left is omitted from the issuer files and is stored in `stocks.json` with `hasCache` false ("No cache yet"). Main Board and GEM rows with `hasCache` false stay in `stocks.json`. The Live page already uses that flag as the bilingual feed.

`cache-meta.json` carries `prototypeStamp`, `stamp`, `snapshot`, `source`, `pairing`, `note`, `exclusions`, `issuerCount`, `pairCount`, and `sourceWindow`, so the Tools page can fill the cutoff and the window without loading filings.
