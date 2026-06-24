# Priority 1 Implementation Report

**Date:** June 24, 2026  
**Scope:** Wire `estimator.py` into the execution pipeline, fix level mismatch, add unit tests.  
**Constraint:** No new features, no UI changes.

---

## Files Changed

| File | Change |
|------|--------|
| `api/main.py` | Import `apply_estimations`; call after `generate_wbs()`; return `plan.start_date` and `plan.end_date` |
| `core/estimator.py` | Fix `allocate_budget()` for L1/L2 WBS structure; roll up parent costs from children; fix rounding remainder on leaves |
| `tests/__init__.py` | New — test package marker |
| `tests/test_estimator.py` | New — 7 unit tests covering budget, dates, dependencies, pipeline integration |
| `PRIORITY_1_REPORT.md` | New — this report |

---

## What Was Fixed

### 1. Estimator wired into pipeline

`POST /generate-plan` now runs:

```
generate_project_id → classify_project → generate_wbs → apply_estimations → serialize
```

Previously `apply_estimations()` existed but was never called. Tasks returned with `start_date: null` and `end_date: null`.

### 2. Every task gets dates

`calculate_timeline()` runs on all tasks via `apply_estimations()`. Each `WBSTask` in the API response now includes:

- `start_date` — `YYYY-MM-DD`
- `end_date` — `YYYY-MM-DD` (inclusive; 5-day task spans 5 calendar days)

### 3. Level mismatch resolved

**Before:** `allocate_budget()` targeted `level == 3` leaves. The WBS generator only produces levels 1 (phases) and 2 (work packages). Budget allocation was a no-op.

**After:** `allocate_budget()` detects the maximum task level dynamically (currently 2) and:

1. Scales all leaf-level costs so they sum exactly to `total_budget`
2. Rolls up each parent phase's `estimated_cost` as the sum of its children

### 4. ProjectPlan returns project-level dates

`apply_estimations()` sets:

- `plan.start_date` = earliest task `start_date`
- `plan.end_date` = latest task `end_date`

The API response now returns these computed values instead of echoing the request `start_date` with `end_date: null`.

---

## Architecture Impact

### Before

```
api/main.py
  └── generate_wbs() → JSON (no dates, budget unnormalized)

core/estimator.py     ← orphan module
core/sap_formatter.py ← still orphan (out of scope)
```

### After

```
api/main.py
  ├── generate_wbs()        → ProjectPlan (structure + template costs)
  └── apply_estimations()   → ProjectPlan (normalized budget + schedule)
        ├── allocate_budget()
        └── calculate_timeline()
```

The pipeline is now **complete for its intended scope**: WBS generation followed by budget normalization and schedule calculation. The API response accurately reflects computed state.

### Data flow (updated)

```
ProjectRequest
  → generate_wbs()     tasks with L1/L2, template costs, dependency graph
  → allocate_budget()  L2 leaves scaled to total_budget; L1 rolled up
  → calculate_timeline()  all tasks get start_date / end_date
  → API JSON response  project + task dates populated
```

---

## Test Coverage

Run with:

```bash
python -m unittest discover -s tests -v
```

| Test | Validates |
|------|-----------|
| `test_leaf_costs_sum_to_total_budget` | L2 leaf costs sum exactly to `total_budget` |
| `test_parent_costs_roll_up_from_children` | Each L1 phase cost equals sum of its L2 children |
| `test_every_task_gets_start_and_end_dates` | All tasks receive `YYYY-MM-DD` dates |
| `test_dependency_ordering` | Dependent tasks start the day after predecessor ends |
| `test_duration_matches_inclusive_end_date` | `end_date - start_date + 1 == duration_days` |
| `test_plan_returns_project_start_and_end_dates` | Plan-level min/max dates set correctly |
| `test_generate_wbs_plus_apply_estimations` | Full pipeline with real template output |

**Result:** 7/7 tests passing.

---

## Remaining Limitations

These are **pre-existing** issues outside Priority 1 scope:

| Limitation | Detail |
|------------|--------|
| **Not real CPM** | `calculate_timeline()` uses topological sort, not forward/backward pass with float or critical path |
| **Sequential-only dependencies** | L2 children depend on previous sibling only; first child in each phase has no dependency on prior phase completion |
| **L1/L2 schedule inconsistency** | Phase-level dates are computed independently from child chains; children in phase N+1 can start before phase N children finish |
| **SAP formatter still unused** | `format_sap_project()` is not exposed via API (Priority 1 item in review mentioned export endpoint — deferred as new feature) |
| **No persistence** | Plans are not saved; IDs reset on restart |
| **Theatrical UI log** | Frontend still shows hardcoded process messages regardless of server state |
| **UI "network activities" label** | Stat strip references L3 tasks that do not exist |
| **Groq optional** | AI task renaming still fails silently without `GROQ_API_KEY` |
| **Synchronous API** | LLM calls block the request thread |
| **No HTTP error semantics** | Failures fall back to template names with 200 OK |

---

## Verification Checklist

- [x] `apply_estimations()` called in `api/main.py`
- [x] All tasks return `start_date` and `end_date`
- [x] `allocate_budget()` works with L1/L2 structure
- [x] Leaf budget sums to `total_budget`
- [x] L1 costs roll up from children
- [x] `ProjectPlan.start_date` and `ProjectPlan.end_date` populated
- [x] API returns computed project dates
- [x] Unit tests for budget, dates, dependencies
- [x] No UI changes
- [x] No new features added
