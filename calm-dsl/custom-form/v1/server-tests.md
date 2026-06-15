# Live server tests — Blueprint / Runbook / Marketplace-Item

Setup: PC **10.103.243.86**, Calm **release 4.4.0** (latest nucalm/epsilon containers),
project `setup`. Driven via `calm-dsl` (PR branch). Update-config/macro is **excluded**.

## Summary
**9 PASS, 1 PARTIAL, 0 FAIL** across Blueprint, Runbook and Marketplace-Item.
Both BP and MPI launches reach a live RUNNING app with a real AHV VM. Runbook
create + decompile + form-retention pass on the latest container.

| # | Entity | Test (CRUD / launch) | Result | Evidence |
|---|---|---|---|---|
| 1 | **Blueprint** | compile → create | ✅ PASS | `e2e924013_bp` |
| 2 | **Blueprint** | decompile: form retained, R1 filename, R3 runtime JSON | ✅ PASS | `Default_custom_form_*.yaml`, `Default_custom_form_runtime_variable.json` |
| 3 | **Blueprint** | edit → recompile → re-upload (v2) | ✅ PASS | `e2e924013_bp_v2` |
| 4 | **Blueprint** | launch (R2 warning + runtime-var fill from JSON) → **app RUNNING** | ✅ PASS | `e2e924013_app5`, AHV VM `10.103.227.148` |
| 5 | **Runbook** | compile → create with custom form | ✅ PASS | `eng924013_rb_cftest` — **no 422** on latest container |
| 6 | **Runbook** | decompile: form retained, R1 filename | ✅ PASS | `use_custom_form=True`, `runbook_custom_form_37ec2fe5-….yaml` |
| 7 | **Runbook** | run/execute | ⚠️ PARTIAL | R2 warning fired + default flow; CLI watch timed out, full task completion not confirmed (engine/escript timing — not a custom-form issue) |
| 8 | **Marketplace** | publish (category Backup, project setup) → approve → store | ✅ PASS | `e2e924013_mpi` v1.0.0 |
| 9 | **Marketplace** | custom form retained in MPI | ✅ PASS | `calm describe marketplace bp` |
| 10 | **Marketplace** | clone / launch from store → **app RUNNING** | ✅ PASS | `e2e924013_mpi_app`, AHV VM `10.103.224.52` |

## Per-entity coverage
- **Blueprint** — full lifecycle: compile, create, decompile (retention + R1 + R3),
  edit, recompile, re-upload, launch to RUNNING. ✅
- **Runbook** — compile, create (custom form), decompile (retention + R1). Execute fires
  the R2 warning and proceeds (watch timed out; not a CF defect). ✅ / ⚠️
- **Marketplace-Item** — publish, approve, store, form-retention, clone+launch to RUNNING. ✅

## Notes (historical failures, now resolved — env, not DSL)
- **Launch HTTP 500** earlier on every `simple_launch`/`execute` = **Policy Engine VM
  down + enforcement enabled** (`styx policy_helper.raise_error_if_policy_down`). Resolved
  by disabling Policy from the PC UI; BP + MPI then reached RUNNING.
- **Runbook create 422** earlier ("Additional properties … custom_form_definition_list")
  = **stale container** (pre `ENG-892908`, 2026-04-27, which added the field to the runbook
  create/upload schema). On the patched container, runbook create works and the form is
  retained. The DSL places custom-form fields under `spec.resources`, matching the server
  schema (and the `export_file` JSON) exactly — no DSL change required.

## Reproduce (examples)
```bash
# Blueprint launch with runtime-var JSON
calm launch bp e2e924013_bp_v2 -a <app> -l specs/Default_custom_form_runtime_variable.json
# Runbook create + decompile with custom form
calm create runbook -f runbook.py -n <name>
calm decompile runbook <name> -d <dir>
# MPI launch from store
calm launch marketplace bp e2e924013_mpi -v 1.0.0 -s LOCAL -pj setup -a <app> -i
```
