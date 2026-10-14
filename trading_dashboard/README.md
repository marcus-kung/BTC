# Bloomberg Trading Challenge — Offline Portfolio Dashboard

This Streamlit app uses the supplied processed WLS candidate workbook, **not Yahoo Finance**. The supplied `Starting Portfolio.xlsx` contains a £/$1,000,000 notional (currency not specified), 20 holdings and weights totalling 100%. Currency is intentionally not assumed.

## Install in existing BTC folder (Mac)

1. Back up your old `BTC/trading_dashboard` folder.
2. Extract this ZIP and copy its contents into `BTC/trading_dashboard`.
3. In the VS Code terminal, from `BTC`:

```bash
source .venv/bin/activate
python -m pip install -r trading_dashboard/requirements.txt
python -m streamlit run trading_dashboard/app.py
```

No internet is used by the dashboard (though package installation requires an internet connection if packages are absent).

## Workflow

- The app automatically loads `data/WLS_Candidate_Shortlist_1_enriched_yahoo_enriched.xlsx` and `data/Starting Portfolio.xlsx` as defaults. Upload newer versions using the sidebar instead.
- The workbook's `Full Rankings` sheet provides 9,105 Yahoo-ticker records including sector, industry and screen metrics. `Top 30 Candidates` supplies country for some holdings. **The Full Rankings sheet has no country field:** elsewhere the dashboard retains country information from your imported portfolio, and shows `Unknown` for missing countries. It does not infer corporate domicile from exchange suffix.
- Search the entire WLS processed list by ticker or name, select a result and add it to the portfolio with 0% initial weight.
- Select any holding and use the weighting slider, then click **Apply weighting**. All other position weights automatically redistribute proportionally to retain a 100% total. Remove the currently selected position, or use **Delete multiple holdings** to remove several stocks in one action; remaining weights are redistributed to total 100%. The last position cannot be removed. Reset to the imported portfolio whenever needed.
- Review position weights, market-value equivalents, country, sector and industry exposures, concentration indicators, and existing screening factors.
- Run static instantaneous shocks to a stock, sector, country or industry.
- Export an Excel workbook with current weights, notional values, screen metrics and exposure tables; the export can be uploaded as the next current-portfolio file.

## Risk and data limitations

- The dashboard uses existing summary metrics, not daily historical returns; it does not calculate pairwise correlations, realised performance, rolling volatility, drawdown of the aggregate portfolio, actual WLS-relative performance or live price-driven weight drift.
- Weighted stock volatility and stock drawdown shown are **not** portfolio-level volatility or drawdown.
- Initial country labels are taken from `Starting Portfolio.xlsx`; different country definitions (listing market versus incorporation) can conflict, so review these labels before reporting exposure.
- All holdings are interpreted in a single notional currency. No FX rates or share quantities are available from the inputs.
- WLS rankings may include incomplete Yahoo metadata. Unknown sector/industry/country values remain labelled Unknown rather than guessed.
- Static shock figures assume no contagion or offsetting price changes.

## Automatic input from Yahoo enrichment

The dashboard now checks these files in order for its default WLS rankings:

1. `BTC/yahoo_enrichment/output/stock_metadata.xlsx` **(preferred; updated by the enrichment script)**
2. `BTC/trading_dashboard/data/stock_metadata.xlsx`
3. `BTC/trading_dashboard/data/WLS_Candidate_Shortlist_1_enriched_yahoo_enriched.xlsx` (legacy fallback)

The uploaded rankings workbook (sidebar) always overrides these defaults. The app reads the latest bytes on each Streamlit rerun, so after the enrichment script finishes writing a new file, refreshing/rerunning the app will load it and reset its portfolio selection to the imported starting portfolio. Do not edit the enrichment file while it is being written.

For the initial holdings the dashboard checks `trading_dashboard/data/Starting Portfolio.xlsx`, then `BTC/data/Starting Portfolio.xlsx`. A sidebar upload overrides the default. If neither exists, upload a portfolio workbook.

Run from your BTC root:

```bash
source .venv/bin/activate
python -m pip install -r trading_dashboard/requirements.txt
python -m streamlit run trading_dashboard/app.py
```

The app does not use Yahoo Finance or make online requests; it reads the enrichment output produced by the separate script.
