"""Fixed model ensemble, purged chronological validation, conservative abstention."""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit


def features(close):
    r = close.pct_change(fill_method=None)
    return pd.DataFrame({'r1': r, 'r5': close.pct_change(5, fill_method=None),
                         'r20': close.pct_change(20, fill_method=None),
                         'r60': close.pct_change(60, fill_method=None),
                         'vol20': r.rolling(20).std(),
                         'ma60': close / close.rolling(60).mean() - 1})


def models():
    return [make_pipeline(StandardScaler(), Ridge(alpha=10)),
            RandomForestRegressor(n_estimators=80, max_depth=4, min_samples_leaf=20,
                                  random_state=42, n_jobs=1)]


def analyse(close, horizon=5, cost_bps=25):
    x = features(close)
    y = close.shift(-horizon) / close - 1
    train = x.assign(target=y).dropna()
    abstain = {'recommendation': 'HOLD', 'qualified': False,
               'reason': 'Insufficient history (minimum 504 labelled sessions)'}
    if len(train) < 504 or x.iloc[-1].isna().any():
        return abstain
    X, Y = train.drop(columns='target'), train.target
    predictions, actual, baseline, folds = [], [], [], []
    for a, b in TimeSeriesSplit(n_splits=5, test_size=63, gap=horizon).split(X):
        preds = []
        for model in models():
            model.fit(X.iloc[a], Y.iloc[a])
            preds.append(model.predict(X.iloc[b]))
        predictions.extend(np.mean(preds, axis=0))
        actual.extend(Y.iloc[b])
        baseline.extend(np.repeat(Y.iloc[a].mean(), len(b)))
        folds.append({'train_end': str(X.index[a[-1]].date()),
                      'test_start': str(X.index[b[0]].date()), 'test_end': str(X.index[b[-1]].date())})
    pred, truth, base = map(np.asarray, (predictions, actual, baseline))
    mse = float(np.mean((pred - truth) ** 2))
    baseline_mse = float(np.mean((base - truth) ** 2))
    zero_mse = float(np.mean(truth ** 2))
    # Overlapping forward returns: evaluate uncertainty on non-overlapping observations.
    residual = (truth - pred)[::horizon]
    uncertainty = float(np.std(residual, ddof=1))
    accuracy = float(np.mean(np.sign(pred[::horizon]) == np.sign(truth[::horizon])))
    latest = []
    for model in models():
        model.fit(X, Y)
        latest.append(float(model.predict(x.iloc[[-1]])[0]))
    forecast = float(np.mean(latest))
    # A heuristic error band, not a calibrated confidence interval or guarantee.
    qualified = mse < min(baseline_mse, zero_mse) and accuracy >= .52
    barrier = 2 * cost_bps / 10000 + uncertainty
    action = 'HOLD'
    if qualified and min(latest) > barrier:
        action = 'BUY'
    elif qualified and max(latest) < -barrier:
        action = 'SELL'
    return dict(recommendation=action, qualified=qualified, forecast=forecast,
                error_band=uncertainty, ridge_forecast=latest[0], forest_forecast=latest[1],
                oos_rmse=mse ** .5, baseline_rmse=baseline_mse ** .5,
                zero_rmse=zero_mse ** .5, direction_accuracy=accuracy,
                nonoverlap_samples=len(residual), folds=folds,
                reason='Validated model agreement beyond costs/error band' if action != 'HOLD'
                else 'Abstain: validation, disagreement or uncertainty/cost threshold',
                momentum_60=float(close.iloc[-1] / close.iloc[-61] - 1),
                annual_vol=float(close.pct_change(fill_method=None).tail(252).std() * np.sqrt(252)))
