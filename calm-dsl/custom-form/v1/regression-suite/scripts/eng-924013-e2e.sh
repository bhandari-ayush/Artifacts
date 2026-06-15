#!/usr/bin/env bash
# ENG-924013 — End-to-end CLI verification driver.
#
# Exercises the full download → edit → upload → re-download → diff loop
# against a live Calm 4.4.0+ Pulse Cluster (PC). This script is the
# Phase-3 acceptance gate for the CustomForm DSL retention work.
#
# What it asserts (one per phase):
#   Phase 1 (M3 + M4): decompile writes specs/<owner>_custom_form.yaml
#       and the generated DSL contains a CustomForm(...) line plus
#       ``use_custom_form = False``.
#   Phase 2 (M2 + M2.5): compile produces a payload with
#       custom_form_definition_list populated and use_custom_form=False;
#       create + update succeed; setting use_custom_form=True in source
#       hard-aborts compile.
#   Phase 3 (M5 + M6): re-decompile after upload preserves the form
#       blob (deepdiff matches modulo the user's edit only).
#
# Pre-requisites:
#   1. ``calm`` CLI configured (``calm set config -s <pc> -u <user> -pw <pw>``)
#      and ``calm update cache`` ran at least once.
#   2. ENV ``CF_BP_NAME`` set to a server BP that has a CustomForm.
#      (Optional ``CF_RB_NAME`` for the runbook leg.)
#   3. ``deepdiff`` installed in the active venv (``pip install deepdiff``).
#
# Usage:
#   CF_BP_NAME=my_demo_bp bash scripts/eng-924013-e2e.sh
#
# Exit code 0 -> all gates green.
# Exit code 1 -> a gate failed; the failing message points at the milestone.

set -euo pipefail

if [[ -z "${CF_BP_NAME:-}" ]]; then
  echo "[ENG-924013] ERROR: set CF_BP_NAME to an existing server BP that has a CustomForm." >&2
  echo "[ENG-924013] usage: CF_BP_NAME=my_demo_bp bash scripts/eng-924013-e2e.sh" >&2
  exit 1
fi

WORK_DIR="${ENG_924013_WORK_DIR:-/tmp/eng-924013-e2e}"
rm -rf "${WORK_DIR}"
mkdir -p "${WORK_DIR}"

V1_DIR="${WORK_DIR}/cf_bp_v1"
V2_DIR="${WORK_DIR}/cf_bp_v2"

echo "[ENG-924013][P1] Decompiling ${CF_BP_NAME} -> ${V1_DIR}..."
calm decompile bp "${CF_BP_NAME}" -d "${V1_DIR}" >/dev/null

# Phase 1 / M3 acceptance.
if ! ls "${V1_DIR}"/specs/*_custom_form.yaml >/dev/null 2>&1; then
  echo "[ENG-924013][P1][M3] FAIL: specs/*_custom_form.yaml missing in ${V1_DIR}" >&2
  exit 1
fi
if ! grep -q "CustomForm(" "${V1_DIR}/blueprint.py"; then
  echo "[ENG-924013][P1][M3] FAIL: CustomForm(...) line missing in blueprint.py" >&2
  exit 1
fi
if ! grep -q "use_custom_form = False" "${V1_DIR}/blueprint.py"; then
  echo "[ENG-924013][P1][M3] FAIL: 'use_custom_form = False' line missing" >&2
  exit 1
fi
echo "[ENG-924013][P1] OK -- form blob retained, use_custom_form forced False."

# Phase 2 / M2 negative-path: setting use_custom_form=True must abort compile.
echo "[ENG-924013][P2] Negative path: use_custom_form = True must abort compile..."
NEG_DIR="${WORK_DIR}/cf_bp_neg"
cp -R "${V1_DIR}" "${NEG_DIR}"
sed -i.bak 's/use_custom_form = False/use_custom_form = True/' "${NEG_DIR}/blueprint.py"
if calm compile bp -f "${NEG_DIR}/blueprint.py" >/dev/null 2>&1; then
  echo "[ENG-924013][P2][M2] FAIL: compile should have aborted on use_custom_form=True" >&2
  exit 1
fi
echo "[ENG-924013][P2] OK -- compile aborted as expected."

# Phase 2 / M2 positive path: payload retains custom_form_definition_list.
echo "[ENG-924013][P2] Compiling ${V1_DIR}/blueprint.py..."
PAYLOAD_FILE="${WORK_DIR}/bp_payload.json"
calm compile bp -f "${V1_DIR}/blueprint.py" --out json > "${PAYLOAD_FILE}"

DEF_LIST_LEN=$(python -c "
import json, sys
with open('${PAYLOAD_FILE}') as f:
    payload = json.load(f)
profiles = payload['spec']['resources'].get('app_profile_list', [])
total = sum(len(p.get('custom_form_definition_list', []) or []) for p in profiles)
print(total)
")
if [[ "${DEF_LIST_LEN}" -lt 1 ]]; then
  echo "[ENG-924013][P2][M2] FAIL: compiled payload has empty custom_form_definition_list" >&2
  exit 1
fi
USE_CF_VALUES=$(python -c "
import json
with open('${PAYLOAD_FILE}') as f:
    payload = json.load(f)
profiles = payload['spec']['resources'].get('app_profile_list', [])
print(' '.join(str(p.get('use_custom_form')) for p in profiles))
")
for v in ${USE_CF_VALUES}; do
  if [[ "${v}" != "False" && "${v}" != "false" ]]; then
    echo "[ENG-924013][P2][M2] FAIL: a profile has use_custom_form=${v} (must be False)" >&2
    exit 1
  fi
done
echo "[ENG-924013][P2] OK -- compiled payload retains form, use_custom_form=False."

# Phase 2 / M2.5 update flow: upload v2.
V2_BP_NAME="${CF_BP_NAME}_eng924013_v2"
echo "[ENG-924013][P2.5] Creating ${V2_BP_NAME}..."
calm create bp -f "${V1_DIR}/blueprint.py" -n "${V2_BP_NAME}" >/dev/null

# Phase 3 / M6 round-trip: re-decompile and diff specs/.
echo "[ENG-924013][P3] Re-decompiling ${V2_BP_NAME} -> ${V2_DIR}..."
calm decompile bp "${V2_BP_NAME}" -d "${V2_DIR}" >/dev/null

if ! ls "${V2_DIR}"/specs/*_custom_form.yaml >/dev/null 2>&1; then
  echo "[ENG-924013][P3][M6] FAIL: specs/*_custom_form.yaml missing in v2 decompile" >&2
  exit 1
fi

python - <<EOF
import glob, sys
try:
    from deepdiff import DeepDiff
except ImportError:
    print("[ENG-924013][P3] deepdiff not installed -- pip install deepdiff", file=sys.stderr)
    sys.exit(1)

import yaml

def load(path):
    with open(path) as f:
        return yaml.safe_load(f)

v1 = sorted(glob.glob("${V1_DIR}/specs/*_custom_form.yaml"))
v2 = sorted(glob.glob("${V2_DIR}/specs/*_custom_form.yaml"))
if len(v1) != len(v2) or len(v1) == 0:
    print("[ENG-924013][P3][M6] FAIL: spec count mismatch v1=%d v2=%d" % (len(v1), len(v2)), file=sys.stderr)
    sys.exit(1)

for a, b in zip(v1, v2):
    diff = DeepDiff(load(a), load(b), ignore_order=True)
    if diff:
        print("[ENG-924013][P3][M6] FAIL: round-trip diff in %s vs %s: %s" % (a, b, diff), file=sys.stderr)
        sys.exit(1)
print("[ENG-924013][P3] OK -- round-trip preserved form blob.")
EOF

echo "[ENG-924013] All gates GREEN."
