# Bloomberg Trading Challenge — Portfolio & Risk Dashboard

An interactive, **offline Streamlit dashboard** for building and reviewing an equity portfolio using pre-processed stock-screening results from the Bloomberg World Large, Mid & Small Cap (WLS) universe.

The application helps a trading team search candidate stocks, adjust portfolio weights, monitor concentration, and test hypothetical losses **without downloading new prices from Yahoo Finance**.

> **Scope:** This is a *portfolio construction and scenario-analysis tool*, not a live trading or performance-tracking system. It does not connect to a brokerage or Bloomberg Terminal.

## What it can do

| Feature | Description |
| --- | --- |
| Import a portfolio | Load holdings and target weights from an Excel workbook such as `Starting Portfolio.xlsx`. |
| Search the WLS universe | Search processed stocks by Yahoo Finance ticker or company name and add them to the portfolio. |
| Adjust holdings | Change a selected stock's target weight with a slider. Other holdings rebalance proportionally to keep total weights at 100%. |
| Remove holdings | Remove one stock or delete several at once; remaining weights are redistributed proportionally. At least one holding must remain. |
| Review exposures | View allocation by position, sector, country, and industry. |
| Evaluate concentration | Review the largest positions and other portfolio concentration measures. |
| Review screening metrics | Examine precomputed momentum, six-month volatility, beta to WLS, drawdown, and screening scores, including weighted summaries. |
| Stress-test scenarios | Model instantaneous shocks to a stock, sector, industry, or country. |
| Export the portfolio | Download the updated allocation and exposure tables as an Excel workbook for later import or team review. |

## Project layout

```text
trading_dashboard/
├── app.py                  # Streamlit user interface
├── portfolio.py            # Import, weighting, exposure and stress-test calculations
├── requirements.txt        # Python dependencies
├── data/
│   ├── Starting Portfolio.xlsx
│   └── WLS_Candidate_Shortlist_1_enriched_yahoo_enriched.xlsx
├── tests/
│   └── test_portfolio.py
└── README.md
```

The two workbooks in `data/` are the default inputs. If those datasets are not included in a shared repository, users must supply compatible versions in that location before launching the app. The sidebar also supports uploading replacement workbooks.

## Getting started

**Prerequisites:** Python 3.10+ and `pip`. These commands work in a macOS/Linux terminal; on Windows, use the corresponding environment activation command.

From the repository's `trading_dashboard` folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

For Windows PowerShell, activate the environment with `.venv\Scripts\Activate.ps1` instead.

Streamlit will display a local URL (usually `http://localhost:8501`). Open it in your browser. **Internet is only needed to install dependencies**, not for the dashboard's portfolio calculations.

If you already use a virtual environment in a parent `BTC/` folder, activate that environment and run `python -m streamlit run trading_dashboard/app.py` from `BTC/` instead.

## Using the dashboard

1. **Load the data.** The app loads the default WLS rankings and starting portfolio from `data/`. Alternatively, upload newer `.xlsx` files in the sidebar.
2. **Review the imported portfolio.** Check that weights, capital/notional and classifications look correct. Imported weights are not silently changed; use the *Normalise portfolio weights to 100%* control if necessary.
3. **Add a company.** Search the processed WLS rankings by name or ticker and click *Add selected stock*. A newly added stock starts at **0%** weight.
4. **Set a target weight.** Choose a holding, move its slider and click *Apply weighting*. The remaining weights change proportionally so that the portfolio stays fully allocated.
5. **Remove holdings if required.** Use *Remove holding* for an individual stock or *Delete selected holdings* to remove several. You can use *Reset to uploaded portfolio* to restore the imported allocations.
6. **Inspect risk exposures.** Review the Positions, Sectors, Countries and Industries tabs, along with portfolio characteristics and concentration measures.
7. **Run a stress test.** Apply a hypothetical price decline to a stock or an entire sector/country/industry and review the estimated impact on portfolio value.
8. **Export your changes.** Select *Download portfolio and exposure workbook*. The exported allocation can be imported again later.

### How weight adjustments work

Suppose a portfolio contains three positions weighted at 50%, 30% and 20%. If the 30% holding is deleted, the other two positions become approximately **71.43%** and **28.57%**, preserving their relative proportions.

Likewise, increasing one holding's weight reduces the others proportionally. These are **target allocation changes**, not executed trades.

## Data sources and requirements

- **WLS candidate workbook:** The `Full Rankings` sheet contains company identifiers and precomputed screening values, including momentum, volatility, beta, drawdown and ranking score. The dataset used to build this project contains approximately **9,105 ranked stock records**, rather than the full original Bloomberg universe.
- **Starting/current portfolio:** An Excel workbook with holdings and allocation weights; the supplied example has **20 holdings** with a notional value of **1,000,000**. The currency is not specified in the source and is not assumed by the application.
- **Company classification:** Sector and industry come from the processed/enriched workbook. Country may come from the imported portfolio or available shortlist metadata. Unresolved classifications are shown as `Unknown`.

The app does not perform new Yahoo Finance lookups. Updating the underlying stock screening or correcting company metadata must be done separately, then supplied through a refreshed workbook.

## Interpretation and limitations

- **Not live performance:** There is no daily price history, transaction ledger, benchmark time series, or live market-data connection. The dashboard **does not** calculate realised portfolio return, return contribution, historical stock correlations, tracking error, or actual relative return against WLS.
- **Risk metrics:** Weighted averages of individual-stock volatility or drawdown **are not** portfolio volatility or drawdown. Weighted beta is an approximation based on the precomputed stock betas.
- **Scenario estimates:** Stress tests use static price shocks and current portfolio weights; they do not model correlations, liquidity, contagion, transaction costs or hedging responses.
- **Geography:** Missing or inconsistent country classifications can understate or misrepresent geographic exposure. Do not infer a company's domicile solely from its ticker suffix.
- **Currency:** Portfolio notional is treated as a single currency; the app does not convert positions using FX rates.
- **Coverage:** Some stocks may have incomplete company metadata or screening metrics; check missing-value indicators before making portfolio decisions.

## Sharing and collaboration

You can run this project locally or deploy it using [Streamlit Community Cloud](https://streamlit.io/cloud). For cloud deployment, host the code in GitHub, include the permitted input workbooks or provide another approved way to upload them, and select `app.py` as the entry point when the repository root is this folder.

**Portfolio edits are session-specific.** Changes to sliders and holdings are not automatically shared between users. Download the portfolio workbook to share a proposed allocation; a collaborative, persistent master portfolio would require additional storage and access controls.

**Data-use note:** Before pushing Excel files to a public GitHub repository or a cloud service, verify that your Bloomberg-derived data and any other licensed datasets may be redistributed or hosted there. If not, keep those files out of the repository and provide them only through an authorised channel.

## Tests

From the dashboard folder, after installing `pytest` if necessary:

```bash
python -m pip install pytest
python -m pytest tests/
```

## Intended use

This project was developed to support stock selection, portfolio construction and risk reviews for the **2026 Bloomberg Trading Challenge**. It is an analytical aid and should not be treated as investment advice or an execution system.
