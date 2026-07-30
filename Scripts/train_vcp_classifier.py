"""
Train a VCP forward-return classifier from historical indicators_daily + breadth_daily.

Target: +15% close-to-close move within 20 trading days (binary).
Features: vcp_score, rs_percentile, distance_to_high_pct, breadth_state (encoded), rvol, trend_score.

Requires: pip install xgboost scikit-learn
Run after a successful database build:
  python Scripts/train_vcp_classifier.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from config import DB_PATH, EXPORTS_DIR

FORWARD_DAYS = 20
TARGET_RETURN_PCT = 15.0


def load_training_frame(min_mcap_cr: float = 1000) -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute(
        f"""
        WITH sequenced AS (
            SELECT i.symbol, i.trade_date, i.close_price, i.vcp_score, i.rs_percentile,
                   i.distance_to_high_pct, i.rvol, i.trend_score, i.is_vcp,
                   lead(i.close_price, {FORWARD_DAYS}) OVER (PARTITION BY i.symbol ORDER BY i.trade_date) AS future_close,
                   m.market_cap_cr
            FROM indicators_daily i
            JOIN stocks_master m USING(symbol)
            WHERE coalesce(m.market_cap_cr, 0) >= ?
        ),
        labeled AS (
            SELECT s.*, b.breadth_state,
                   CASE WHEN (future_close / nullif(close_price, 0) - 1) * 100 >= {TARGET_RETURN_PCT} THEN 1 ELSE 0 END AS hit_target
            FROM sequenced s
            LEFT JOIN breadth_daily b USING(trade_date)
            WHERE future_close IS NOT NULL AND is_vcp
        )
        SELECT * FROM labeled
        """,
        [min_mcap_cr],
    ).fetchdf()
    con.close()
    return df


def train(df: pd.DataFrame) -> dict:
    try:
        from sklearn.compose import ColumnTransformer
        from sklearn.metrics import classification_report, roc_auc_score
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder
        from xgboost import XGBClassifier
    except ImportError as exc:
        raise SystemExit("Install dependencies: pip install xgboost scikit-learn") from exc

    feature_cols = ["vcp_score", "rs_percentile", "distance_to_high_pct", "rvol", "trend_score", "breadth_state"]
    data = df.dropna(subset=feature_cols + ["hit_target"]).copy()
    if data.empty:
        raise RuntimeError("No training rows after filtering.")

    data = data.sort_values("trade_date")
    x = data[feature_cols]
    y = data["hit_target"].astype(int)

    pre = ColumnTransformer(
        [("breadth", OneHotEncoder(handle_unknown="ignore"), ["breadth_state"])],
        remainder="passthrough",
    )
    model = Pipeline(
        steps=[
            ("pre", pre),
            ("clf", XGBClassifier(max_depth=4, n_estimators=200, learning_rate=0.05, eval_metric="logloss")),
        ]
    )

    split = TimeSeriesSplit(n_splits=3)
    scores = []
    for train_idx, test_idx in split.split(x):
        model.fit(x.iloc[train_idx], y.iloc[train_idx])
        proba = model.predict_proba(x.iloc[test_idx])[:, 1]
        scores.append(roc_auc_score(y.iloc[test_idx], proba))

    model.fit(x, y)
    proba_all = model.predict_proba(x)[:, 1]
    report = classification_report(y, (proba_all >= 0.5).astype(int), output_dict=True)

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "forward_days": FORWARD_DAYS,
        "target_return_pct": TARGET_RETURN_PCT,
        "rows": len(data),
        "positive_rate": float(y.mean()),
        "cv_roc_auc_mean": float(np.mean(scores)),
        "classification_report": report,
    }
    meta_path = EXPORTS_DIR / "vcp_classifier_metrics.json"
    meta_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    try:
        import joblib

        joblib.dump(model, EXPORTS_DIR / "vcp_classifier.joblib")
    except ImportError:
        pass

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Train VCP +15% / 20d classifier")
    parser.add_argument("--min-mcap", type=float, default=1000)
    args = parser.parse_args()
    df = load_training_frame(args.min_mcap)
    metrics = train(df)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()