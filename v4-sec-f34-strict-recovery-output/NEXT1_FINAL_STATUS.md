# V4 NEXT-1 SEC PIT F3/F4 — STATUS AFTER EXACT RECOVERY

## Locked rules
- Population: NONFIN_MAIN. SIC 6000–6799 remains separate.
- Existing-confirmed corporate-action exclusions only: AAWW, ABMD, STMP.
- New delisting/M&A lookup or recovery: 0.
- 2023 formation / future outcomes / US3700: not opened or used.
- SEC accepted-time PIT cutoff remains enforced.
- Missing factors are not imputed.
- Coverage threshold remains 80% at every planned snapshot.

## Exact SEC recovery result on confirmed-eligible rows
- F3 confirmed coverage range: **71.34%–76.37%**. It is below 80% at all 12 snapshots.
- F4 confirmed coverage range: **91.22%–96.90%**. It is above 80% at all 12 snapshots.

These are confirmed-eligibility results, not the final historical N_t gate.

## Eligibility-UNKNOWN bounds
Eligibility UNKNOWN rows are not silently excluded.

- F3 coverage bounds across snapshots:
  - minimum lower bound: **41.67%**
  - minimum upper bound: **81.95%**
- F4 coverage bounds across snapshots:
  - minimum lower bound: **71.58%**
  - minimum upper bound: **95.20%**

Therefore neither factor can be given a final full-universe PASS/FAIL while historical eligibility UNKNOWN remains unresolved:
- F3: **UNRESOLVED_ELIGIBILITY**
- F4: **UNRESOLVED_ELIGIBILITY**

F4 passes on confirmed rows, but early-snapshot worst-case bounds remain below 80%.
F3 fails on confirmed rows, but its optimistic eligibility bound remains above 80%, so it is not yet mathematically DEAD under the frozen full-rigor rule.

## Semantic mappings retained
- F4: WeightedAverageNumberOfShareOutstandingBasicAndDiluted allowed after diluted and before basic fallback.
- F3 CFO: ContinuingOperations + DiscontinuedOperations only when period-aligned; continuing-only is not total CFO.
- F3 revenue: RegulatedAndUnregulatedOperatingRevenue allowed as total operating revenue.
- PaymentsToAcquireProductiveAssets rejected because it is broader than PP&E capex.
- Component revenue tags rejected unless exhaustive aggregation is proven.

SEC CompanyFacts supplies standard-taxonomy facts applying to the entire filing entity; it is used only with accepted-time PIT filtering.

## Next bottleneck
NEXT-1 factor reconstruction is complete. The remaining blocker for the actual 80% gate is historical eligibility UNKNOWN (market-cap / price / liquidity), not delisting or M&A discovery.
