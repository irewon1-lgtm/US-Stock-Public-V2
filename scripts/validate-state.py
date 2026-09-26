#!/usr/bin/env python3
from __future__ import annotations
import json
import sys
from pathlib import Path

METRIC_KEYS = [
    "Revenue_TTM_YoY_Pct","Gross_Margin_TTM_Pct","Operating_Margin_TTM_Pct",
    "Net_Margin_TTM_Pct","ROA_TTM_Pct","FCF_Yield_TTM_Pct",
    "Price_Sales_TTM","Shares_Change_YoY_Pct","Drawdown_52W_Pct"
]

def norm(v):
    return str(v or "").strip().upper().replace(".", "-").replace("/", "-")

state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
universe = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
config = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8")) if len(sys.argv) > 3 else None

rows = state.get("records") or []
expected = {norm(t) for t in universe.get("tickers") or []}
actual = {norm(r.get("ticker")) for r in rows}
source_by_key = {m["key"]: m["source"] for m in (config or {}).get("metrics", [])}

assert state.get("schema") == "US_PUBLIC_V2_STATE_V1"
assert state.get("recordCount") == len(rows) == 3700
assert len(actual) == 3700 and actual == expected
assert state.get("metricCount") == 9

numeric8 = 0
for row in rows:
    metrics = row.get("metrics") or {}
    assert set(metrics) == set(METRIC_KEYS)
    assert "TTM_PER" not in metrics
    numeric = 0

    for key in METRIC_KEYS:
        cell = metrics[key]
        assert cell.get("status") in {"NUMERIC","NA_BASIS","HOLD"}
        assert cell.get("updatedAt")
        assert "source" in cell
        assert set(cell) == {"value","status","source","updatedAt"}
        if source_by_key:
            assert cell.get("source") == source_by_key[key]

        if cell.get("status") == "NUMERIC":
            assert isinstance(cell.get("value"), (int,float))
            numeric += 1
        else:
            assert cell.get("value") is None

    if numeric >= 8:
        numeric8 += 1

assert numeric8 == 3700, numeric8
print(json.dumps({
    "ok": True,
    "recordCount": len(rows),
    "metricCount": 9,
    "records8plusNumeric": numeric8,
    "ttmPerPresent": False,
    "compactMetricCells": True,
    "metricCellFields": ["value","status","source","updatedAt"]
}, separators=(",", ":")))
