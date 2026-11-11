# Bilingual HKEXnews filings refresh

Studio command for the cache behind `bilingual-hkex-filings.html`. The page reads a published snapshot. It does not call HKEXnews. This script is the offline refresh. It does not write the Live `cache-meta.json`, `stocks.json`, `tiers.json`, or `filings/` files, and it does not download PDF bodies. It does not write a whole-market `filings-cache.json.gz`.

The Wednesday and Sunday run, around 08:30 Asia/Hong_Kong, is the Grok Bot routine on the studio computer. Do not add a GitHub Actions cron that pulls HKEXnews.

## Commands

Work files go to `data/hkex-filings-work/` (gitignored), or to `--work`, or to `HKEX_FILINGS_ROOT`. Do not point that directory at the repository root.

```bash
python3 scripts/refresh-bilingual-hkex-filings.py --self-test
python3 scripts/refresh-bilingual-hkex-filings.py pull --work DIR
python3 scripts/refresh-bilingual-hkex-filings.py build --work DIR
python3 scripts/refresh-bilingual-hkex-filings.py check --work DIR
```

`all` is pull, then build, then check. It does not gzip.

```bash
python3 scripts/refresh-bilingual-hkex-filings.py all --work DIR
```

`check` exits 1 when the build is not shippable: a pull failed, the Main+GEM equity universe is empty, issuer or pair counts sit outside ±20% of the 11 November 2026 Live snapshot (3,072 issuers, 273,418 pairs, after the Debt and Structured Products strip), `tiers.json` still contains debt or structured-product chips, an issuer with no remaining pairs is in the hasCache universe, or the issuer files do not match `cache-meta.json`.

## Lookback and the monthly full re-pull

An incremental pull reuses monthly raw files outside the lookback. It always re-pulls the last 14 calendar days in Asia/Hong_Kong, including today, even when those days sit inside a monthly file already marked complete. Headline revisions in that window replace the cached row.

That lookback does not repair an older rewrite. About once a month, re-pull the whole three-year window on the studio computer:

```bash
python3 scripts/refresh-bilingual-hkex-filings.py pull --full-repull --work DIR
python3 scripts/refresh-bilingual-hkex-filings.py build --work DIR
python3 scripts/refresh-bilingual-hkex-filings.py check --work DIR
```

The window is today minus three years in Asia/Hong_Kong. 29 February falls back to 28 February. Disk language C is Traditional Chinese and is requested as `lang=zh`. English is `lang=E`.

## What build writes

Inside the work directory, and nowhere on the Live site:

- `cache-meta.json`, with `stamp`, `prototypeStamp`, `snapshot`, `source`, `pairing`, `note`, `exclusions`, `issuerCount`, `pairCount`, and `sourceWindow`
- `stocks.json`, with `c`, `i`, `n`, `nt`, and `hasCache`
- `tiers.json`, with the debt and structured-product chips already removed
- `filings/{prefix}/{code}.json.gz`, one compact JSON file per `hasCache` issuer, gzipped at compresslevel 9. `prefix` is the first two digits of the five-digit code. Each file has `code`, `stockId`, `nameEn`, `nameTc`, `snapshot`, `sourceWindow`, `stats`, and `filings`. An issuer with `hasCache` false has no file.

```bash
python3 scripts/refresh-bilingual-hkex-filings.py gzip --work DIR
```

`gzip` only confirms that ship set after the quality gate would pass. It does not write `filings-cache.json.gz`. Copying `cache-meta.json`, `stocks.json`, `tiers.json`, and `filings/` onto the site is a later pull request.

## Cookies

If the studio keeps a Netscape `cookies.txt`, put it at `data/_local/cookies.txt` inside the work directory. The script reads it and never writes it. Do not commit it.

## What the build strips

Contains match, including a cancelled or reissued prefix, not an exact or startswith match:

- Monthly Returns, the whole Tier 1, including 月報表 and 51500
- Next Day Disclosure share buybacks (other NDRs stay, including the standard form title "changes in issued share capital and/or share buybacks" / 已發行股本及/或股份購回; AGM repurchase circulars stay)
- Warrants, options, and 牛熊證 (CBBCs)
- Debt and Structured Products (債券及結構性產品), code 70000, and documents-on-display types 57000, 58000, and 59000

Those debt chips are removed from `tiers.json` as well as from filing rows. An issuer with no paired filings left is omitted from the per-issuer filings files and is stored in `stocks.json` with `hasCache` false, so it is outside the hasCache universe. The Live page already uses that flag as the bilingual feed.
