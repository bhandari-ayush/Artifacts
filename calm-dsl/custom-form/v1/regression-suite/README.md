# ENG-924013 — Regression Test Suite

Out-of-tree regression harness for ENG-924013 (CustomForm DSL retention +
AHV NIC macro redesign). **Do not push this directory into the
calm-dsl repo** — it shells out to `calm-dsl`'s code via the project
venv, mutates fixtures in `artifacts/`, and writes throw-away outputs.

## Layout

```
eng-924013-regression/
├── README.md                 # this file
├── conftest.py               # pytest fixtures (paths, venv python, seed BPs)
├── helpers.py                # mutate / compile / round-trip utilities
├── fixtures/
│   ├── bp_cf_seed/           # snapshot of calm-dsl/bp_cf at start of run
│   └── rb_cf_seed/           # synthetic runbook DSL with CustomForm
├── scripts/
│   └── run_regression.sh     # full e2e shell driver
├── tests/
│   ├── test_normal_macros.py        # @@{var}@@ on every supported AHV field
│   ├── test_json_macros.py          # JSON-bearing macros on json / json-per-item fields
│   ├── test_custom_form.py          # ergonomic + auto-resolve + retention
│   ├── test_multi_profile.py        # N profiles, each with own CustomForm
│   ├── test_runbook.py              # rb_cf flow
│   └── test_negative_paths.py       # use_custom_form=True hard-error etc
└── artifacts/                       # gitignored throwaway outputs
```

## Running

```bash
cd ~/Workspace/eng-924013-regression
bash scripts/run_regression.sh                 # full driver (mutate + compile)
~/Workspace/calm-dsl/venv/bin/python -m pytest tests/ -v --no-cov   # 50+ pytest cases
```

## What it asserts (per phase)

| Phase | What | Where |
|---|---|---|
| P1 (M3 + M4) | decompile writes `specs/<owner>_custom_form.yaml`; DSL emits the lazy `CustomForm(name="...")` | `tests/test_custom_form.py` |
| P2 (M2 + M2.5) | compile populates `custom_form_definition_list`; forces `use_custom_form=False`; aborts on `True` | `tests/test_custom_form.py`, `tests/test_negative_paths.py` |
| P3 (M5 + M6) | macros on every AHV-NIC field; multi-profile CustomForm; round-trip diff matches | `tests/test_normal_macros.py`, `tests/test_json_macros.py`, `tests/test_multi_profile.py` |

## Pre-requisites

- `calm-dsl` checked out at `~/Workspace/calm-dsl` with its venv at
  `~/Workspace/calm-dsl/venv`.
- `~/Workspace/calm-dsl/bp_cf/` populated by a prior
  `calm decompile bp bp_cf -d bp_cf` (any BP with a custom form works).
- `calm init dsl` already done -- the suite does NOT make network calls
  by default; the optional `RUN_LIVE_CALM=1` env var enables a live
  `calm create bp` smoke.
