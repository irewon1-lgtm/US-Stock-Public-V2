#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.public_site_fundamentals import collect_ticker

METRIC_KEYS = [
    "Revenue_TTM_YoY_Pct",
    "Gross_Margin_TTM_Pct",
    "Operating_Margin_TTM_Pct",
    "Net_Margin_TTM_Pct",
    "ROA_TTM_Pct",
    "FCF_Yield_TTM_Pct",
    "Price_Sales_TTM",
    "Shares_Change_YoY_Pct",
    "Drawdown_52W_Pct",
]

IDENTITY_KEYS = [
    "ticker", "company", "category", "sector", "industry",
    "cik", "exchange"
]

LOG_LOCK = threading.Lock()

def log_json(value):
    with LOG_LOCK:
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)

def norm_ticker(value):
    return str(value or "").strip().upper().replace(".", "-").replace("/", "-")

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def write_json(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def metric_is_fresh(cell, day):
    c = cell or {}
    return c.get("status") in {"NUMERIC", "NA_BASIS"} and str(c.get("asOf") or "")[:10] == day

def compact_metric(cell, source, updated_at):
    src = cell or {}
    status = src.get("status") if src.get("status") in {"NUMERIC", "NA_BASIS", "HOLD"} else "HOLD"
    return {
        "value": src.get("value") if status == "NUMERIC" else None,
        "status": status,
        "source": source,
        "updatedAt": updated_at,
    }

def compact_existing_state(state, source_by_key):
    for row in state.get("records") or []:
        metrics = row.get("metrics") or {}
        compacted = {}
        for key in METRIC_KEYS:
            cell = metrics.get(key) or {}
            compacted[key] = compact_metric(
                cell,
                source_by_key[key],
                cell.get("updatedAt") or row.get("lastSuccessfulRefreshAt") or state.get("generatedAt") or utc_now(),
            )
        row["metrics"] = compacted
        row.pop("freshMetricCount", None)
        row.pop("collectionErrors", None)
    return state

def seed_state(universe, seed, source_by_key):
    seed_rows = seed.get("records") or []
    seed_map = {norm_ticker(r.get("ticker")): r for r in seed_rows if r.get("ticker")}
    generated_at = seed.get("generatedAt") or utc_now()
    records = []

    for ticker in universe["tickers"]:
        t = norm_ticker(ticker)
        src = seed_map.get(t)
        if not src:
            raise RuntimeError("PUBLIC_V2_SEED_MISSING:" + t)

        metrics = {}
        for key in METRIC_KEYS:
            if key not in (src.get("metrics") or {}):
                raise RuntimeError("PUBLIC_V2_SEED_METRIC_MISSING:" + t + ":" + key)
            metrics[key] = compact_metric(
                src["metrics"][key],
                source_by_key[key],
                generated_at,
            )

        row = {k: src.get(k) for k in IDENTITY_KEYS if src.get(k) is not None}
        row["ticker"] = t
        row["metrics"] = metrics
        row["numericCount"] = sum(m.get("status") == "NUMERIC" for m in metrics.values())
        row["resolvedCount"] = sum(m.get("status") in {"NUMERIC", "NA_BASIS"} for m in metrics.values())
        row["lastAttemptAt"] = None
        row["lastSuccessfulRefreshAt"] = generated_at
        records.append(row)

    if len(records) != 3700 or len({r["ticker"] for r in records}) != 3700:
        raise RuntimeError("PUBLIC_V2_SEED_CARDINALITY")

    return {
        "schema": "US_PUBLIC_V2_STATE_V1",
        "version": "Public V2",
        "generatedAt": generated_at,
        "recordCount": 3700,
        "metricCount": 9,
        "selectionPolicy": "OLDEST_ATTEMPT_FIRST_FAIR_ROTATION",
        "records": records,
        "summary": {},
        "seed": {
            "sourceSchema": seed.get("schema"),
            "sourceGeneratedAt": seed.get("generatedAt"),
            "note": "Initial V2 state copied from previous verified snapshot; TTM PER removed."
        }
    }

def validate_state(state, universe, source_by_key):
    rows = state.get("records") or []
    expected = [norm_ticker(t) for t in universe["tickers"]]
    if state.get("recordCount") != 3700 or len(rows) != 3700:
        raise RuntimeError("PUBLIC_V2_STATE_COUNT")
    tickers = [norm_ticker(r.get("ticker")) for r in rows]
    if len(set(tickers)) != 3700 or set(tickers) != set(expected):
        raise RuntimeError("PUBLIC_V2_STATE_IDENTITY")

    for row in rows:
        metrics = row.get("metrics") or {}
        if set(metrics) != set(METRIC_KEYS):
            raise RuntimeError("PUBLIC_V2_STATE_METRICS:" + norm_ticker(row.get("ticker")))
        if "TTM_PER" in metrics:
            raise RuntimeError("PUBLIC_V2_TTM_PER_LEAK")

        for key, cell in metrics.items():
            if cell.get("status") not in {"NUMERIC", "NA_BASIS", "HOLD"}:
                raise RuntimeError("PUBLIC_V2_BAD_STATUS:" + row["ticker"] + ":" + key)
            if cell.get("source") != source_by_key[key]:
                raise RuntimeError("PUBLIC_V2_BAD_SOURCE:" + row["ticker"] + ":" + key)
            if not cell.get("updatedAt"):
                raise RuntimeError("PUBLIC_V2_MISSING_UPDATE_TIME:" + row["ticker"] + ":" + key)
            if set(cell) != {"value", "status", "source", "updatedAt"}:
                raise RuntimeError("PUBLIC_V2_NON_COMPACT_CELL:" + row["ticker"] + ":" + key)
            if cell.get("status") == "NUMERIC" and not isinstance(cell.get("value"), (int, float)):
                raise RuntimeError("PUBLIC_V2_BAD_NUMERIC:" + row["ticker"] + ":" + key)

def summarize(state):
    rows = state["records"]
    by_metric = {}
    for key in METRIC_KEYS:
        cells = [r["metrics"][key] for r in rows]
        updates = [c.get("updatedAt") for c in cells if c.get("updatedAt")]
        by_metric[key] = {
            "numeric": sum(c.get("status") == "NUMERIC" for c in cells),
            "naBasis": sum(c.get("status") == "NA_BASIS" for c in cells),
            "hold": sum(c.get("status") == "HOLD" for c in cells),
            "oldestUpdatedAt": min(updates) if updates else None,
            "latestUpdatedAt": max(updates) if updates else None,
        }

    attempts = [r.get("lastAttemptAt") for r in rows if r.get("lastAttemptAt")]
    successes = [r.get("lastSuccessfulRefreshAt") for r in rows if r.get("lastSuccessfulRefreshAt")]
    return {
        "recordCount": len(rows),
        "heldRecordCount": sum(bool(r.get("refreshHold")) for r in rows),
        "metricCount": 9,
        "totalMetricCells": len(rows) * 9,
        "numericMetrics": sum(m.get("status") == "NUMERIC" for r in rows for m in r["metrics"].values()),
        "resolvedMetrics": sum(m.get("status") in {"NUMERIC", "NA_BASIS"} for r in rows for m in r["metrics"].values()),
        "records9of9Numeric": sum(r.get("numericCount") == 9 for r in rows),
        "records8plusNumeric": sum(r.get("numericCount", 0) >= 8 for r in rows),
        "oldestAttemptAt": min(attempts) if attempts else None,
        "latestAttemptAt": max(attempts) if attempts else None,
        "oldestSuccessfulRefreshAt": min(successes) if successes else None,
        "latestSuccessfulRefreshAt": max(successes) if successes else None,
        "byMetric": by_metric,
    }

def merge_refresh(previous, fresh, day, attempt_at, source_by_key):
    """Commit a ticker atomically, or retain its last verified record with a visible hold."""
    fresh_metrics = fresh.get("metrics") or {}
    merged_metrics = {}
    fresh_count = 0
    for key in METRIC_KEYS:
        raw_new = fresh_metrics.get(key) or {}
        if metric_is_fresh(raw_new, day):
            merged_metrics[key] = compact_metric(raw_new, source_by_key[key], attempt_at)
            fresh_count += 1
        else:
            merged_metrics[key] = copy.deepcopy(previous["metrics"][key])

    candidate_numeric = sum(c.get("status") == "NUMERIC" for c in merged_metrics.values())
    previous_numeric = sum(c.get("status") == "NUMERIC" for c in previous["metrics"].values())
    prior_hold = previous.get("refreshHold") or {}
    # A fetch failure must not erase a known rejected N/A observation merely
    # because the retained old value still happens to be numeric.
    unresolved = {
        m["key"]: copy.deepcopy(m)
        for m in prior_hold.get("regressedMetrics") or []
        if not metric_is_fresh(fresh_metrics.get(m["key"]), day)
    }
    regressions = dict(unresolved)
    for key in METRIC_KEYS:
        if previous["metrics"][key].get("status") == "NUMERIC" and merged_metrics[key].get("status") != "NUMERIC":
            raw = fresh_metrics.get(key) or {}
            regressions[key] = {
                "key": key,
                "previousStatus": "NUMERIC",
                "observedStatus": merged_metrics[key]["status"],
                "observedValue": merged_metrics[key]["value"],
                "source": source_by_key[key],
                "reason": raw.get("reason") or "최신 관측에서 숫자 지표가 확인되지 않음",
                "observedAt": attempt_at,
            }
    if previous_numeric >= 8 and (candidate_numeric < 8 or unresolved):
        out = copy.deepcopy(previous)
        out["lastAttemptAt"] = attempt_at
        out["refreshHold"] = {
            "reason": "COVERAGE_BELOW_8_OF_9" if candidate_numeric < 8 else "PREVIOUS_COVERAGE_HOLD_UNRESOLVED",
            "firstHeldAt": prior_hold.get("firstHeldAt") or attempt_at,
            "attemptedAt": attempt_at,
            "candidateNumericCount": candidate_numeric,
            "minimumNumericCount": 8,
            "regressedMetrics": [regressions[k] for k in METRIC_KEYS if k in regressions],
            "collectionErrors": list(fresh.get("collectionErrors") or []),
        }
        return out

    out = {**previous}
    out.update({k: fresh.get(k) for k in IDENTITY_KEYS if fresh.get(k) is not None})
    out["ticker"] = norm_ticker(previous["ticker"])
    out["metrics"] = merged_metrics
    out["numericCount"] = candidate_numeric
    out["resolvedCount"] = sum(c.get("status") in {"NUMERIC", "NA_BASIS"} for c in merged_metrics.values())
    out["lastAttemptAt"] = attempt_at
    if fresh_count:
        out["lastSuccessfulRefreshAt"] = attempt_at
    out.pop("refreshHold", None)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--status", required=True)
    ap.add_argument("--count", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    universe = read_json(args.universe)
    config = read_json(args.config)
    if universe.get("recordCount") != 3700 or len(universe.get("tickers") or []) != 3700:
        raise RuntimeError("PUBLIC_V2_UNIVERSE_INVALID")
    if config.get("metricCount") != 9:
        raise RuntimeError("PUBLIC_V2_CONFIG_INVALID")

    metric_config = config.get("metrics") or []
    if [m.get("key") for m in metric_config] != METRIC_KEYS:
        raise RuntimeError("PUBLIC_V2_METRIC_ORDER_INVALID")
    source_by_key = {m["key"]: m["source"] for m in metric_config}

    state_path = Path(args.state)
    if state_path.exists():
        state = compact_existing_state(read_json(state_path), source_by_key)
    else:
        state = seed_state(universe, read_json(args.seed), source_by_key)

    validate_state(state, universe, source_by_key)
    state_map = {norm_ticker(r["ticker"]): r for r in state["records"]}

    ordered = sorted(
        state["records"],
        key=lambda r: (
            r.get("lastAttemptAt") is not None,
            r.get("lastAttemptAt") or "",
            norm_ticker(r.get("ticker")),
        ),
    )
    count = max(1, min(int(args.count), 1000, len(ordered)))
    selected = ordered[:count]

    started_at = utc_now()
    day = started_at[:10]
    workers = max(1, min(int(args.workers), 4))
    updated = {}
    fatal = []

    def one(previous):
        ticker = norm_ticker(previous["ticker"])
        identity = {k: previous.get(k) for k in IDENTITY_KEYS if previous.get(k) is not None}
        identity["ticker"] = ticker
        fresh = collect_ticker(identity, day, previous)
        out = merge_refresh(previous, fresh, day, utc_now(), source_by_key)
        if out.get("refreshHold"):
            log_json({"event": "PUBLIC_V2_REFRESH_HELD", "ticker": ticker, **out["refreshHold"]})
        return ticker, out

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one, row): row["ticker"] for row in selected}
        for i, fut in enumerate(as_completed(futs), 1):
            ticker = futs[fut]
            try:
                t, row = fut.result()
                updated[t] = row
            except Exception as e:
                fatal.append({"ticker": ticker, "error": type(e).__name__ + ":" + str(e)[:180]})
                prev = copy.deepcopy(state_map[ticker])
                prev["lastAttemptAt"] = utc_now()
                if prev.get("refreshHold"):
                    prev["refreshHold"]["attemptedAt"] = prev["lastAttemptAt"]
                    prev["refreshHold"]["collectionErrors"] = [fatal[-1]["error"]]
                updated[ticker] = prev

            if i % 100 == 0:
                log_json({"processed": i, "selected": count, "fatal": len(fatal)})

    universe_order = [norm_ticker(t) for t in universe["tickers"]]
    state["records"] = [updated.get(ticker, state_map[ticker]) for ticker in universe_order]
    state["generatedAt"] = utc_now()
    if os.environ.get("GITHUB_SHA"):
        state["sourceCommit"] = os.environ["GITHUB_SHA"]
    state["recordCount"] = 3700
    state["metricCount"] = 9
    state["lastBatch"] = {
        "startedAt": started_at,
        "finishedAt": state["generatedAt"],
        "selectedCount": count,
        "workers": workers,
        "fatalRecordCount": len(fatal),
        "heldInBatchCount": sum(bool(r.get("refreshHold")) for r in updated.values()),
        "selectedTickersSha256": hashlib.sha256(
            "\n".join(norm_ticker(r["ticker"]) for r in selected).encode()
        ).hexdigest(),
    }
    state["summary"] = summarize(state)
    validate_state(state, universe, source_by_key)

    if state["summary"]["records8plusNumeric"] != 3700:
        raise RuntimeError(
            "PUBLIC_V2_COVERAGE_BELOW_8_OF_9:" + str(state["summary"]["records8plusNumeric"])
        )

    status = {
        "ok": True,
        "version": "Public V2",
        "batchSize": count,
        "workers": workers,
        "startedAt": started_at,
        "finishedAt": state["generatedAt"],
        "fatalRecordCount": len(fatal),
        "heldInBatchCount": sum(bool(r.get("refreshHold")) for r in updated.values()),
        "sourceCommit": state.get("sourceCommit"),
        "heldRecordCount": state["summary"]["heldRecordCount"],
        "heldRecords": [
            {"ticker": r["ticker"], "lastSuccessfulRefreshAt": r.get("lastSuccessfulRefreshAt"), **r["refreshHold"]}
            for r in state["records"] if r.get("refreshHold")
        ],
        "records9of9Numeric": state["summary"]["records9of9Numeric"],
        "records8plusNumeric": state["summary"]["records8plusNumeric"],
        "oldestAttemptAt": state["summary"]["oldestAttemptAt"],
        "latestAttemptAt": state["summary"]["latestAttemptAt"],
        "oldestSuccessfulRefreshAt": state["summary"]["oldestSuccessfulRefreshAt"],
        "latestSuccessfulRefreshAt": state["summary"]["latestSuccessfulRefreshAt"],
        "metricUpdates": {
            key: {
                "oldestUpdatedAt": state["summary"]["byMetric"][key]["oldestUpdatedAt"],
                "latestUpdatedAt": state["summary"]["byMetric"][key]["latestUpdatedAt"],
            }
            for key in METRIC_KEYS
        },
        "selectedTickersSha256": state["lastBatch"]["selectedTickersSha256"],
        "fatalSample": fatal[:20],
    }

    write_json(args.state, state)
    write_json(args.status, status)
    print(json.dumps(status, ensure_ascii=False, separators=(",", ":")), flush=True)

if __name__ == "__main__":
    main()
