# V4 NEXT-1 SEC PIT F3/F4 — FINAL STATUS

## Scope lock
- Population: NONFIN_MAIN only. SIC 6000–6799 remains separate.
- Existing-confirmed corporate-action exclusions only: AAWW, ABMD, STMP.
- New delisting/M&A lookup/API calls: 0.
- 2023 formation opened: NO.
- Future outcomes/targets used: NO.
- US3700 used: NO.
- SEC PIT accepted-time cutoff: enforced.
- Missing factor imputation: none.
- Coverage gate: >=80% at every planned snapshot.

## Semantic recovery lock
- F4: WeightedAverageNumberOfShareOutstandingBasicAndDiluted allowed after diluted, before basic fallback.
- F3 CFO: ContinuingOperations + DiscontinuedOperations only when period-aligned; continuing-only is not accepted as total CFO.
- F3 revenue: RegulatedAndUnregulatedOperatingRevenue accepted as total operating revenue.
- PaymentsToAcquireProductiveAssets rejected for final F3 because it is broader than PP&E capex.
- Component revenue tags rejected unless exhaustive aggregation is proven.

SEC CompanyFacts is limited to non-custom taxonomy facts applying to the entire filing entity, so it is compatible with the conservative whole-entity/segment rule.

## Confirmed-eligibility coverage after exact recovery

| Snapshot | N | F3 usable | F3 cov | F3 >=80 | F4 usable | F4 cov | F4 >=80 |
|---|---:|---:|---:|:---:|---:|---:|:---:|
| 2020-03-31 | 637 | 458 | 71.90% | FAIL | 613 | 96.23% | PASS |
| 2020-06-30 | 679 | 496 | 73.05% | FAIL | 655 | 96.47% | PASS |
| 2020-09-30 | 673 | 514 | 76.37% | FAIL | 644 | 95.69% | PASS |
| 2020-12-31 | 740 | 557 | 75.27% | FAIL | 698 | 94.32% | PASS |
| 2021-03-31 | 841 | 608 | 72.29% | FAIL | 799 | 95.01% | PASS |
| 2021-06-30 | 827 | 602 | 72.79% | FAIL | 776 | 93.83% | PASS |
| 2021-09-30 | 795 | 579 | 72.83% | FAIL | 738 | 92.83% | PASS |
| 2021-12-31 | 820 | 585 | 71.34% | FAIL | 748 | 91.22% | PASS |
| 2022-03-31 | 795 | 592 | 74.47% | FAIL | 749 | 94.21% | PASS |
| 2022-06-30 | 773 | 588 | 76.07% | FAIL | 749 | 96.90% | PASS |
| 2022-09-30 | 736 | 559 | 75.95% | FAIL | 710 | 96.47% | PASS |
| 2022-12-30 | 731 | 557 | 76.20% | FAIL | 708 | 96.85% | PASS |

## Gate result
- F3: COVERAGE GATE FAIL / DEAD under frozen full-rigor V4. Minimum coverage 71.34%.
- F4: COVERAGE GATE PASS. Minimum coverage 91.22%.
- The 80% rule was not lowered.
- No new corporate-action discovery was used to improve the denominator.

Generated from target order SHA-256:
`82322d8ba460d54a375fb3a19320af9e9b21313a3f14b6257f6c5c1b273b1596`
