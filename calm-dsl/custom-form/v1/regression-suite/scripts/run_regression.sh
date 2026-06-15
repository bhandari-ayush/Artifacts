#!/usr/bin/env bash
# ENG-924013 regression driver.
#
# What this does:
#   1. Snapshots the current calm-dsl/bp_cf into artifacts/<run-id>/seed/
#   2. Mutates the BP -- normal macros + JSON macros on every supported field
#   3. compile()s each variant via the calm-dsl venv python
#   4. (optional) ``calm create bp -f <variant>.py --name bp_cf_v<N>`` for
#      a live smoke (gated by RUN_LIVE_CALM=1; off by default)
#   5. (optional) ``calm decompile bp bp_cf_v<N>`` to verify retention
#   6. Runs the pytest suite and prints a pass/fail summary
#
# Usage:
#   bash scripts/run_regression.sh                  # offline mode
#   RUN_LIVE_CALM=1 bash scripts/run_regression.sh  # also exercise calm CLI
#
# This script is intentionally NOT part of the calm-dsl repo -- it is a
# free-standing regression harness. Do not commit it inside calm-dsl.

set -uo pipefail

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------

REGRESSION_ROOT="$( cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd )"
WORKSPACE_ROOT="$( cd "${REGRESSION_ROOT}/.." && pwd )"
CALM_DSL_ROOT="${WORKSPACE_ROOT}/calm-dsl"
VENV_PY="${CALM_DSL_ROOT}/venv/bin/python"
LIVE_BP_DIR="${CALM_DSL_ROOT}/bp_cf"

RUN_ID="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="${REGRESSION_ROOT}/artifacts/${RUN_ID}"
mkdir -p "${RUN_DIR}"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

ok()      { printf "  \033[32m[ OK ]\033[0m %s\n" "$*"; }
warn()    { printf "  \033[33m[WARN]\033[0m %s\n" "$*"; }
fail()    { printf "  \033[31m[FAIL]\033[0m %s\n" "$*"; }
section() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }

# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------

section "Sanity checks"
if [[ ! -x "${VENV_PY}" ]]; then
    fail "calm-dsl venv python missing at ${VENV_PY}"
    exit 1
fi
ok "venv python -> ${VENV_PY}"

if [[ ! -d "${REGRESSION_ROOT}/fixtures/bp_cf_seed" ]]; then
    fail "bp_cf_seed fixture missing at ${REGRESSION_ROOT}/fixtures/bp_cf_seed"
    exit 1
fi
ok "bp_cf_seed fixture present"

if [[ ! -d "${REGRESSION_ROOT}/fixtures/rb_cf_seed" ]]; then
    warn "rb_cf_seed fixture missing -- runbook tests will skip"
else
    ok "rb_cf_seed fixture present"
fi

# ---------------------------------------------------------------------------
# Variants we generate -- one per macro class to keep failures localised
# ---------------------------------------------------------------------------

section "Generating BP variants under ${RUN_DIR}/"

cat > "${RUN_DIR}/_gen.py" <<'PY'
import os
import shutil
import sys
from pathlib import Path

REGRESSION_ROOT = Path(os.environ["REGRESSION_ROOT"])
RUN_DIR = Path(os.environ["RUN_DIR"])
SEED = REGRESSION_ROOT / "fixtures" / "bp_cf_seed"

sys.path.insert(0, str(REGRESSION_ROOT))
from helpers import write_blueprint_with_macros, normal_macro  # noqa: E402


def make_variant(label, **kwargs):
    out = RUN_DIR / "variants" / label
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SEED, out)
    write_blueprint_with_macros(out / "blueprint.py", out / "blueprint.py", **kwargs)
    print("[gen] {}".format(out))


make_variant(
    "00_baseline",
)
make_variant(
    "10_normal_subnet",
    nic_subnet_macro=normal_macro("subnet_var"),
)
make_variant(
    "11_normal_vpc",
    nic_subnet_macro=normal_macro("subnet_var"),
    nic_vpc_macro=normal_macro("vpc_var"),
)
make_variant(
    "12_normal_mac",
    nic_subnet_macro=normal_macro("subnet_var"),
    nic_mac_macro=normal_macro("mac_var"),
)
make_variant(
    "13_normal_ip",
    nic_subnet_macro=normal_macro("subnet_var"),
    nic_ip_macro=normal_macro("ip_var"),
)
make_variant(
    "14_normal_combined",
    nic_subnet_macro=normal_macro("subnet_var"),
    nic_vpc_macro=normal_macro("vpc_var"),
    nic_mac_macro=normal_macro("mac_var"),
    nic_ip_macro=normal_macro("ip_var"),
    vm_name_macro=normal_macro("vm_name_var"),
    cluster_macro=normal_macro("cluster_var"),
)
# JSON-macro variants -- the macro string itself IS a JSON dump.
make_variant(
    "20_json_subnet",
    nic_subnet_macro=normal_macro("subnet_json_var"),
)
make_variant(
    "21_json_ip_endpoint",
    nic_subnet_macro=normal_macro("subnet_var"),
    nic_ip_macro=normal_macro("ip_json_var"),
)
PY

REGRESSION_ROOT="${REGRESSION_ROOT}" RUN_DIR="${RUN_DIR}" "${VENV_PY}" "${RUN_DIR}/_gen.py" \
    | tee "${RUN_DIR}/gen.log"
ok "$(grep -c '^\[gen\]' "${RUN_DIR}/gen.log") variants generated"

# ---------------------------------------------------------------------------
# Compile-only verification (no live calls)
# ---------------------------------------------------------------------------

section "Compile each variant"

cat > "${RUN_DIR}/_compile_check.py" <<'PY'
import os
import sys
import json
from pathlib import Path

REGRESSION_ROOT = Path(os.environ["REGRESSION_ROOT"])
RUN_DIR = Path(os.environ["RUN_DIR"])
sys.path.insert(0, str(REGRESSION_ROOT))

from helpers import compile_blueprint_payload, load_blueprint_module  # noqa: E402

failures = []
for variant_dir in sorted((RUN_DIR / "variants").iterdir()):
    bp_py = variant_dir / "blueprint.py"
    try:
        bp = load_blueprint_module(bp_py)
        payload = compile_blueprint_payload(bp)
        # Persist the compiled cdict for inspection.
        with open(RUN_DIR / "{}.compiled.json".format(variant_dir.name), "w") as fh:
            json.dump(payload, fh, indent=2)
        prof = payload["spec"]["resources"]["app_profile_list"][0]
        cf_count = len(prof.get("custom_form_definition_list") or [])
        print(
            "[compile] {:<25}  cf_count={}  use_custom_form={}".format(
                variant_dir.name, cf_count, prof.get("use_custom_form")
            )
        )
        # Guards.
        assert prof["use_custom_form"] is False, "use_custom_form must be False"
        assert cf_count == 1, "every variant should keep its CustomForm"
    except Exception as exc:
        print("[compile] {:<25}  FAILED: {}".format(variant_dir.name, exc))
        failures.append((variant_dir.name, str(exc)))

if failures:
    print("\nFAILED variants:")
    for name, err in failures:
        print("  - {}: {}".format(name, err))
    sys.exit(1)
PY

REGRESSION_ROOT="${REGRESSION_ROOT}" RUN_DIR="${RUN_DIR}" "${VENV_PY}" "${RUN_DIR}/_compile_check.py" \
    | tee "${RUN_DIR}/compile.log"
COMPILE_RC=${PIPESTATUS[0]}

if [[ $COMPILE_RC -eq 0 ]]; then
    ok "all variants compiled cleanly"
else
    fail "compile step had failures (rc=${COMPILE_RC}); see ${RUN_DIR}/compile.log"
fi

# ---------------------------------------------------------------------------
# Optional live calm CLI smoke
# ---------------------------------------------------------------------------

if [[ "${RUN_LIVE_CALM:-0}" == "1" ]]; then
    section "Live calm CLI smoke (RUN_LIVE_CALM=1)"
    pushd "${LIVE_BP_DIR}" > /dev/null
    UNIQ="reg_$(date +%s)"
    if "${CALM_DSL_ROOT}/venv/bin/calm" create bp -f blueprint.py --name "${UNIQ}" 2>&1 \
        | tee "${RUN_DIR}/live_create.log"; then
        ok "calm create bp succeeded as ${UNIQ}"
        if "${CALM_DSL_ROOT}/venv/bin/calm" decompile bp "${UNIQ}" -d "${RUN_DIR}/live_decompile" 2>&1 \
            | tee "${RUN_DIR}/live_decompile.log"; then
            ok "calm decompile bp succeeded"
            if [[ -f "${RUN_DIR}/live_decompile/specs/Default_custom_form.yaml" ]]; then
                ok "specs/Default_custom_form.yaml round-tripped"
            else
                fail "specs/Default_custom_form.yaml was NOT round-tripped"
            fi
        fi
    else
        fail "calm create bp failed; see ${RUN_DIR}/live_create.log"
    fi
    popd > /dev/null
else
    warn "skipping live calm CLI smoke (set RUN_LIVE_CALM=1 to enable)"
fi

# ---------------------------------------------------------------------------
# Pytest
# ---------------------------------------------------------------------------

section "Running pytest suite"
pushd "${REGRESSION_ROOT}" > /dev/null
if "${VENV_PY}" -m pytest tests/ --no-cov -q -p no:warnings | tee "${RUN_DIR}/pytest.log"; then
    PYTEST_RC=0
    ok "pytest passed"
else
    PYTEST_RC=1
    fail "pytest failed (see ${RUN_DIR}/pytest.log)"
fi
popd > /dev/null

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

section "Summary"
printf "  artifacts: %s\n" "${RUN_DIR}"
TOTAL_TESTS=$(grep -Eo '[0-9]+ passed' "${RUN_DIR}/pytest.log" | head -1 | awk '{print $1}')
printf "  pytest:    %s tests passed\n" "${TOTAL_TESTS:-?}"
printf "  compile:   exit code %s\n" "${COMPILE_RC}"
printf "  pytest rc: %s\n" "${PYTEST_RC}"

if [[ ${COMPILE_RC} -eq 0 && ${PYTEST_RC} -eq 0 ]]; then
    printf "\n  \033[1;32mALL GREEN\033[0m\n"
    exit 0
else
    printf "\n  \033[1;31mFAILED\033[0m -- inspect %s\n" "${RUN_DIR}"
    exit 1
fi
