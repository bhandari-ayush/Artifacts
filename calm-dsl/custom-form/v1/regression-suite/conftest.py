"""ENG-924013 regression conftest.

Sets up shared paths, venv discovery, and seed-BP/runbook fixtures.
Designed to be run from this directory's venv (the calm-dsl venv) so
``import calm.dsl.builtins`` resolves without any sys.path massage at
test collection time.
"""

import os
import shutil
import sys
from pathlib import Path

import pytest


REGRESSION_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = REGRESSION_ROOT.parent
CALM_DSL_ROOT = WORKSPACE_ROOT / "calm-dsl"
ARTIFACTS_DIR = REGRESSION_ROOT / "artifacts"
FIXTURES_DIR = REGRESSION_ROOT / "fixtures"
# Stable seed -- snapshotted into fixtures/ so tests don't depend on the
# user's working bp_cf checkout.
SEED_BP_DIR = FIXTURES_DIR / "bp_cf_seed"
LIVE_BP_DIR = CALM_DSL_ROOT / "bp_cf"


# Make sure pytest can import calm.dsl.* even when the user invokes
# ``pytest tests/`` directly without prefacing with the venv python.
if str(CALM_DSL_ROOT) not in sys.path:
    sys.path.insert(0, str(CALM_DSL_ROOT))


@pytest.fixture(scope="session")
def workspace_root():
    return WORKSPACE_ROOT


@pytest.fixture(scope="session")
def calm_dsl_root():
    assert CALM_DSL_ROOT.is_dir(), (
        "calm-dsl checkout missing at {} -- regression suite expects it as a "
        "sibling of this directory".format(CALM_DSL_ROOT)
    )
    return CALM_DSL_ROOT


@pytest.fixture(scope="session")
def seed_bp_dir(calm_dsl_root):
    if not SEED_BP_DIR.is_dir():
        pytest.skip(
            "Seed BP fixture {} missing. Snapshot it from a working "
            "bp_cf via "
            "``cp -R calm-dsl/bp_cf eng-924013-regression/fixtures/bp_cf_seed``"
            ".".format(SEED_BP_DIR)
        )
    return SEED_BP_DIR


@pytest.fixture(scope="session")
def live_bp_dir():
    """Live calm-dsl/bp_cf -- only used by the run_regression.sh-style
    end-to-end smoke. Tests that don't need this should use ``seed_bp_dir``.
    """

    if not LIVE_BP_DIR.is_dir():
        pytest.skip("Live bp_cf checkout missing at {}".format(LIVE_BP_DIR))
    return LIVE_BP_DIR


@pytest.fixture(scope="session")
def artifacts_dir():
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_DIR


@pytest.fixture
def bp_workdir(tmp_path, seed_bp_dir):
    """Per-test copy of the seed BP. Tests mutate this freely."""

    target = tmp_path / "bp_cf"
    shutil.copytree(seed_bp_dir, target)
    return target


@pytest.fixture
def stub_calm_version(monkeypatch):
    """Mock ``Version.get_version`` so M0 4.4.0 gate doesn't block tests."""

    from calm.dsl.store.version import Version

    monkeypatch.setattr(Version, "get_version", staticmethod(lambda _key: "4.4.0"))
    yield "4.4.0"


@pytest.fixture(autouse=True)
def _restore_cwd():
    """``load_blueprint_module`` deliberately leaves cwd at the BP dir so
    relative ``read_spec`` / ``CustomForm`` auto-resolve work during a
    subsequent ``compile()``. Pytest's tmp_path teardown removes the dir,
    so we must restore cwd between tests to avoid ``OSError: [Errno 2]
    No such file or directory`` on the next ``getcwd``.
    """

    import os

    prev = os.getcwd()
    yield
    try:
        os.chdir(prev)
    except FileNotFoundError:
        os.chdir(REGRESSION_ROOT)
