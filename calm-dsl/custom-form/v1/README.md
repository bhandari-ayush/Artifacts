# calm-dsl — CustomForm retention (ENG-924013) — test artifacts, v1

Test suites, results and server-test report backing the **calm-dsl** PR for
**CustomForm retention on Blueprint / Runbook / Marketplace-Item**
(compile · decompile · CRUD · launch).

> Scope: **Blueprint, Runbook, Marketplace-Item** only.
> The update-config / macro blueprint work is **out of scope** here and will be
> handled in a separate PR — no update-config tests are included in this artifact.

## Contents
```
calm-dsl/custom-form/v1/
  README.md             # this file
  server-tests.md       # live-server tests on PC 10.103.243.86 (RB/BP/MPI): what ran, pass/fail/why
  regression-suite/     # the calm-dsl change test suite (pytest)
    tests/  fixtures/  helpers.py  conftest.py  scripts/  README.md
  results/
    unit-results.txt        # calm-dsl tests/unit (custom_form + decompile)  -> 61 passed
    regression-results.txt  # regression-suite                                -> 65 passed
```

## Results at a glance
| Suite | Passed | Failed | Where |
|---|---|---|---|
| Unit (`calm-dsl/tests/unit`: custom_form, decompile specs, http_var) | **61** | 0 | `results/unit-results.txt` |
| Regression (`regression-suite/tests`) | **65** | 0 | `results/regression-results.txt` |
| **Total offline** | **126** | **0** | |
| Live server (RB/BP/MPI) | **9 pass, 1 partial, 0 fail** | — | `server-tests.md` |

## What the PR fix includes (validated by these suites)
- **R1** custom-form spec YAML filename carries the form name
  (`<profile>_custom_form_<uuid>.yaml`, `runbook_custom_form_<uuid>.yaml`).
- **R2** `use_custom_form` is **retained** through compile/CRUD; at launch a warning is
  logged ("custom form launch not supported yet") and the default launch flow proceeds.
- **R3** decompile emits `specs/<ctx>_custom_form_runtime_variable.json`; launch can
  consume it via `-l/--launch_params` (works for static **and** dynamic vars).
- **R4** `init_runbook_dir` reverted to the 3-arg signature (specs/ still created).
- **R5** `CustomForm(spec_file="forms/x.yaml")` reads a user-provided spec path.
- Decompile robustness fix in `builtins/models/entity.py` (snapshot the dict before a
  validation-mismatch `del`, avoids "dictionary changed size during iteration").

## How to run the regression suite
```bash
cd <this>/regression-suite
# point at a calm-dsl venv with the PR branch installed
source /path/to/calm-dsl/venv/bin/activate
python -m pytest tests/ -o addopts="" -q
```
Unit suite (in the calm-dsl repo):
```bash
cd /path/to/calm-dsl && source venv/bin/activate
python -m pytest tests/unit/test_custom_form.py \
  tests/unit/test_decompile_runbook_specs_dir.py \
  tests/unit/test_decompile_http_var_with_basic_auth.py -o addopts="" -q
```

Environment for the live tests: PC `10.103.243.86`, Calm **release 4.4.0** (latest
containers), project `setup`. See `server-tests.md`.
