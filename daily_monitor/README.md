# Daily portfolio research

This project refreshes the 20 positions imported from `portfolio(1).csv`, evaluates stock signals, screens a bounded portion of the existing WLS candidate workbook, and produces a morning report. It **never executes trades**. The input CSV is a positions snapshot: updating prices never changes quantities or invents cash. Update it after manual trades/corporate actions.

## Run and outputs

From the repository root, using Python 3.12 or later:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r daily_monitor/requirements.txt
PYTHONPATH=.:trading_dashboard python -m pytest daily_monitor/tests trading_dashboard/tests -q
python -m daily_monitor.run
# Holdings-only diagnostic:
python -m daily_monitor.run --max-screen 0
```

`daily_monitor/output/portfolio.csv` preserves original purchase/position columns and adds completed-session closes, retrieval time, currency/scale, FX, USD value, weights, availability and recommendations. Original `Current Price`, `Date`, etc. remain the **imported snapshot**, not live fields: use `latest_close` and `price_session`. `screen.csv` records every attempted holding/candidate with forecast and validation diagnostics; `audit.json` holds folds, errors, input configuration, fundamentals, timestamps, news links and scenario details. `report.md` is the concise latest report, with a dated copy for history. Missing prices remain missing; old exported values are never silently used for new signals. Weights are suppressed unless all positions can be valued.

## Reuse and review of existing code

Inspected the repository before implementation. Reuses `trading_dashboard.portfolio.read_rankings`, including its ticker normalisation, deduplication and descriptive enrichment. Default input is `yahoo_enrichment/output/stock_metadata.xlsx`, with 9,105 historical candidate rows. Existing `yahoo_enrichment/enrich_yahoo.py` provides reusable mappings and company metadata; its skip-completed cache has no daily freshness guarantee and its per-ticker rate counter cannot enforce HTTP-level limits inside yfinance, so the monitor has its own dated cache/transport. The dashboard's weight/stress utilities describe static allocations, not historical portfolio covariance. Existing notebook rankings/parquet history are useful reference material, but were not passed off as current market prices or leakage-free backtests. Dashboard files and historical notebooks are preserved.

## Scheduling and storage

`.github/workflows/portfolio-monitor.yml` tests PRs without fetching live data. Once merged to the default branch, it runs daily at **07:15 Europe/London**, including weekends to accommodate global markets and report closures. Native IANA timezone scheduling follows BST/GMT. Manual Actions dispatch is also available. Reports appear in the Actions job summary and as 90-day artifacts; the job commits only `daily_monitor/output/` on the checked-out branch. It caches raw fetched data separately. Concurrency prevents overlapping runs on one branch. Permissions are read-only except the report job's `contents: write`; it uses the built-in Actions token, with no secrets in source. If repository rules prevent bot pushes, the upload still provides the report; configure a permitted output branch/change the commit step rather than bypassing protections. The schedule is best effort, may be delayed/dropped, requires the workflow on the default branch, and public-repository schedules can be disabled after 60 days of inactivity. Changing the configured local morning time requires updating the workflow schedule too.

Current holdings/session handling uses exchange-calendars with a 30-minute post-close buffer, public holidays and local timezones. Today’s unfinished daily candle is excluded. A market closed for a holiday/weekend uses its latest completed session and shows that date. A missing expected bar blocks the symbol. Unknown exchanges, including Kuwait, require an explicitly verified calendar mapping; there is no weekday guess for these. US exchange suffix-less stocks use XNYS (shared regular US equity holiday schedule); cross-listed/special-session securities need review. A 07:15 London run can precede Asia's close, so the latest completed session can be yesterday even when an imported CSV contains later prices.

## Yahoo ingestion and FX

A single custom `curl_cffi.Session` is passed to all yfinance tickers, including FX. It counts **actual transport request attempts**, pauses one second before attempts 21, 41, etc., and retries 429/selected 5xx responses twice with 2/4-second backoff. Requests are sequential; yfinance's hidden auth/metadata calls count too. This is the requested batching policy, **not a claim about Yahoo's official allowed rate**. Daily equity caches are keyed by symbol/completed session and retrieval date; stale cache data do not qualify as fresh. FX history is refreshed per currency per run. No stale fallback is silently used.

Raw `Close` values positions; `Adj Close` trains models and computes return histories, accounting for vendor splits/dividends. The imported quantities are assumed current. Quote currency is required. Common minor units (GBp/GBX, ZAc, ILA) are explicitly scaled; Kuwait currency/scale require an override such as `{"ACICO.KW": {"currency": "KWD", "scale": 0.001}}` **only if verified against the vendor quote units**, not simply because the ticker is Kuwaiti. Prices and FX are positive/finite checked. FX `CCYUSD=X` uses completed prior UTC dates, backward alignment only and maximum four calendar days of tolerance. Native-currency forecasts are not forecasts of USD FX movements. Portfolio covariance uses adjusted USD-converted price returns on intersecting observed dates without return forward filling. Global closes are asynchronous, so correlations and risk estimates have timing bias; they are research estimates, not an executable synchronized portfolio valuation.

## Models and evidence thresholds

Fixed feature set: 1/5/20/60-session returns, 20-session volatility and deviation from the 60-session mean. Target is the next five sessions' adjusted-price return. Fixed Ridge regression and shallow random forest are fitted independently for each security; standardisation is fitted inside each Ridge training fold. At least 504 labelled sessions are required. Five chronological 63-session test folds have a five-observation purge gap so training forward labels cannot overlap the test start. Folds and OOS RMSE are recorded, compared with both a training-mean baseline and zero-return baseline. No random train/test shuffle or full-history preprocessing is used. Final fitting uses only matured historical labels, then predicts from the latest complete feature row.

BUY/SELL requires lower OOS MSE than both baselines, at least 52% nonoverlapping directional accuracy, and both models agreeing beyond round-trip costs plus one nonoverlapping OOS residual standard deviation. Otherwise HOLD means **abstain**, not a positive endorsement. The band is a heuristic, not a calibrated confidence interval. Overlapping labels are used for fitting/MSE; uncertainty/directional diagnostics are sampled every five sessions. No hyperparameter search, calibrated probabilities, statistically established alpha or profitable strategy backtest is claimed. The fixed validation results remain subject to selection/regime risk. Current universe membership has survivorship bias; current fundamental/news snapshots are never backfilled into historical training.

## Your portfolio guidelines

The $1 million is **initial capital on 12 October 2026**, not available cash or current NAV. Config records this distinction. Normal maximum weight is 10%, with 12.5% as a hard review barrier. The 12–15 holding count is a target, not an instruction to sell five current positions automatically. Effective holdings is reported as `1/sum(w²)` and, when common return history exists, as the cash-excluded normalised version. Annual volatility, correlations, and a static 30% equity-downside scenario are included. Position-specific downside appears in proposed alternatives. This stress is not VaR or a forecast.

Conviction points combine team fundamental/event-risk scores (-1/0/+1), low/high volatility (<20%/+1, >40%/-1 annualised) and weak/strong correlation (<0.3/+1, >0.7/-1). With no team fundamental assessment, current profitable/growing vendor data earns +1, loss/contraction or debt/equity >200 earns -1, missing/neutral data earns 0. Ratios are sector-dependent and can be misleading for banks. The points are transparent heuristics, not statistical confidence. Caps of 5%, 8% and 10% apply to low/medium/high points. Sizing uses a 1/15 equal-weight anchor times signal/error strength and inverse volatility (20% reference); low evidence or high volatility can reduce a suggested size **below** its tier, rather than forcing a minimum allocation. New names require explicit team approval in `team_scores.csv` after fundamental, valuation, event-risk and supply-chain checks. Current news is supporting context for that review, not automatically interpreted as causation.

Commission is **USD 0.005 per share per buy or sell leg**, confirmed by the owner. Cash is **USD 0**. For stock-level thresholds, the one-way fee fraction is `0.005 / current_USD_share_price`; the round-trip threshold includes it twice. Replacement scenarios charge the sold and purchased stocks separately using their respective USD share prices. Purchase size is reduced to pay both fees out of sale proceeds (or cash), so zero available cash does not silently fund commissions. Optional `other_cost_bps_one_way` is 0 until further instructions; spreads/slippage/taxes are not assumed confirmed.

Replacement analysis enumerates cash-funded buys and sales from current holdings as **alternative** scenarios, not cumulative orders. A SELL signal is not required to reduce an existing holding if a conservative improvement clears all constraints. Scenario allocation cannot exceed the suggested size, funding, 10% position cap or configured 10% two-sided turnover limit. Uses Ledoit–Wolf shrinkage covariance from at least 126 common sessions and five-day expected return minus transaction costs and risk penalty; estimated volatility may not increase. Candidate/funding prediction error is also penalised. Minimum net utility improvement is 0.2% of NAV over the forecast horizon. All holdings and candidate require qualified forecasts and complete metadata. Fees reduce scenario NAV and purchase size; displayed weights/exposures are normalised to post-fee NAV. Share quantities remain fractional research estimates; executable lot sizes are not modelled. Taxes, lot sizes, market impact, settlement, contest eligibility and liquidity must be checked manually.

Active exposures are **absolute deviations from WLS weights**, checked for sectors (15 percentage points), industries (15 points provisional), major countries (10 points), minor countries (5 points), including benchmark categories with zero holdings. These use conservative lower ends of the requested geographic ranges. Populate `benchmark_exposures.csv` with `dimension` = `sector`, `industry` or `country`, `category`, decimal `weight`, and `major_country` true/false. Each dimension must sum to 1 with unique categories. Corporate country from Yahoo is not revenue/supply-chain geography; team review must assess those economic exposures. If such a manual assessment is missing, do not treat domicile limits as complete geographic risk control.

## News, fundamentals, WLS and source limits

Yahoo's per-symbol news endpoint supplies up to eight headlines; the monitor retains the last three days, records publisher/date/link, and does not fetch full articles. A headline link may lead to gated content; the code never bypasses it or claims to have read it. Missing headlines do not prove no news. No FT subscription/content retrieval is assumed. Fundamental context uses available P/E, revenue growth, margin, debt/equity, free cash flow and market cap; missing data remain missing. Publication/update dates are not reliably supplied for all ratios, so the audit records retrieval times, not invented financial-statement dates.

The repository workbook is a **historical candidate snapshot**, not a verified complete current WLS membership feed. Default 150 rotating non-held candidates plus all holdings are attempted each morning, with coverage/rotation offset in each report; unsupported calendars and provider failures reduce usable coverage. Set `max_screen` to the authorised universe size for a full attempt, allowing substantially greater runtime/request use; a 150-name rotation takes roughly 61 days to revisit 9,105 rows. Rankings determine rotation order but do not replace current signals. Maintain an authorised current universe workbook with `Full Rankings`/Ticker and a verified membership date; there is no automatic scraping of Bloomberg membership. Configure `benchmark_ticker` only for an authorised **actual WLS** data source; otherwise WLS-relative performance is explicitly unavailable. No ETF or world-index proxy is silently substituted. Benchmark performance shown, when available, is a constant-current-weight research comparison on common historical dates, not actual portfolio P&L since inception.

Primary references:

- [yfinance history and data API](https://ranaroussi.github.io/yfinance/reference/index.html), [adjustment/download semantics](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)
- [scikit-learn TimeSeriesSplit and gap](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
- [exchange-calendars schedules](https://github.com/gerrymanoim/exchange_calendars)
- [GitHub schedule semantics and limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

Yahoo/yfinance are not exchange-grade guaranteed services. Review Yahoo's applicable data-use terms before redistributing data; request failures and vendor revisions are normal. The repo is public: this workflow stores holdings and reports publicly as requested. Cache files stay untracked. No credentials, brokerage connections, automated orders or promises of performance are included.

## Remaining setup inputs (reported as blockers)

1. **Cash and commission are supplied:** cash USD 0; commission USD 0.005 per share for each buy/sell leg. Remaining non-commission trading costs, initial active industry limit, turnover/risk parameters and contest rules await confirmation; keep `constraints_confirmed` false until those are supplied.
2. **ACICO reconciliation.** You confirmed 168,430 shares at 0.572 and a $30,000 purchase on 12 October. Multiplication gives 96,341.96 in the quoted purchase currency; these inputs do not reconcile as USD without currency/unit/quantity reconciliation. The $30,000 is recorded as a stated total USD cost, with `reconciled: false`. No exchange rate/quote scale is invented. Confirm quote currency/scale and an actual Kuwait exchange calendar before enabling its current valuation. `calendar_overrides` accepts a verified exchange-calendars name or an authoritative session file: `{"ACICO.KW": {"sessions_csv": "path/to/kuwait_sessions.csv", "valid_through": "YYYY-MM-DD", "source": "official source URL"}}`. Session CSV columns are `session_date,close_utc` (UTC timestamp with offset); include all open days through `valid_through`, sorted, including local weekends, holidays and early closes correctly. Expired coverage is rejected. No Kuwait schedule is invented; supply the verified file before enabling valuation.
3. **WLS membership/as-of date, sector/industry/country weights and actual benchmark series/ticker** from a source you may use. Set `universe_verified_as_of` only after verification. Empty exposure files deliberately block portfolio replacements.
4. **Team fundamental/event-risk approval** for new names, using `team_scores.csv` (`symbol,fundamental_score,event_risk_score,approved,notes`). No judgement is fabricated for supply chains, impending events or contested data.
5. **Purchase units and corporate actions.** Set `purchase_units_confirmed` only after review. Cost/P&L remains suppressed by default; even when enabled, `local_price_return` is a quote-currency price comparison, not realised return or FX-adjusted total P&L.

Reports and price refreshes still run with blockers. They must not be mistaken for a fully configured investable strategy. Merge/review the PR before enabling its default-branch schedule. No secrets are required for publicly available Yahoo data; any later authorised paid feed should use GitHub Actions secrets, never committed credentials.


## Entering WLS country, industry and sector weights

Edit **`daily_monitor/data/benchmark_exposures.csv`**, already linked in `config.json`. It has starter rows for all three dimensions. Replace blank categories/weights and add one row per category. Use verified **WLS benchmark** classifications/weights, not portfolio allocations or the number of companies in a candidate shortlist. Category names must match the names used by the monitor. Do not estimate benchmark weights from `WLS_Candidate_Shortlist_1_enriched_yahoo_enriched.xlsx`.

- `dimension`: `country`, `industry` or `sector`.
- `category`: the country/industry/sector name.
- `weight`: decimal fraction, e.g. `0.25` for 25%. Every dimension must separately total `1` (the combined file totals `3`).
- `major_country`: `true` or `false` for countries, blank for industry/sector. This selects the configured active country limit.

Check the file without fetching prices:

```sh
python -m daily_monitor.exposures daily_monitor/data/benchmark_exposures.csv
```

The checker rejects missing categories/weights, invalid dimensions, negative/over-1/nonfinite weights, duplicate categories, invalid country flags, and totals other than 1 (tolerance 0.000001). It never silently renormalises weights. Blank starter rows intentionally remain invalid until real benchmark data are entered; the morning report lists these input errors without crashing. A valid weight file does not automatically verify membership, confirm competition rules or resolve other pending prerequisites. Previously generated reports retain their original run configuration; the next run uses the new cash and commission settings.
