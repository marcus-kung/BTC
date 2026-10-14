# Yahoo Finance metadata enrichment

Fetch company name, sector and industry for Yahoo tickers in the **Full Rankings** sheet, preserving rankings and other columns. Lookups are cached and can resume after interruptions.

## Files

```text
yahoo_enrichment/
├── enrich_yahoo.py
├── requirements.txt
├── README.md
├── WLS_Candidate_Shortlist_1_enriched_yahoo_enriched.xlsx  # existing source; optional
├── yahoo_lookup_progress.csv                               # existing cache; optional
└── output/
    ├── stock_metadata.xlsx   # latest enriched workbook
    ├── lookup_cache.csv      # resumable lookup results
    └── unresolved.csv        # unresolved / partially classified tickers
```

The output filenames are **fixed on every run**, including retries. The folder is created automatically. The source Excel file is not overwritten.

## Running from BTC root

```bash
source .venv/bin/activate
python -m pip install -r yahoo_enrichment/requirements.txt
python yahoo_enrichment/enrich_yahoo.py \
  --input "yahoo_enrichment/WLS_Candidate_Shortlist_1_enriched_yahoo_enriched.xlsx" \
  --retry-failed --batch-size 10 --batch-pause 180 --delay 5
```

By default the updated script **copies your existing `yahoo_lookup_progress.csv` into `output/lookup_cache.csv` once** if no new cache exists. Keep the new cache for later runs. If you previously passed a different `--cache` path, supply that exact path again to avoid losing progress.

Optional explicit paths: `--output path/to/stock_metadata.xlsx --cache path/to/lookup_cache.csv`. All existing batch and rate-limit flags still work.

**Caution:** If `--input` points to your most recent enriched file, newly retrieved data is added while preserving existing cells. If your input is an older source file, existing classifications will be populated from the cache. Don't rename or remove either cache before checking its contents.

## Clean up existing files

After confirming the new `output/stock_metadata.xlsx` contains your data and the cache has your prior progress, archive or remove obsolete `_v2.xlsx` and `_unresolved.csv` duplicates. Do not delete the original source workbook or progress CSV before verification.
