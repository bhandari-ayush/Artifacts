"""Runbook CustomForm coverage (synthetic rb_cf).

Mirrors the BP profile tests but at the RunbookService layer -- where
the server actually carries the custom_form_* fields per
``calm/src/calm/server/styx/yamls/apps/runbook.yaml`` runbook_resources.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from helpers import synth_custom_form_yaml  # noqa: E402

from calm.dsl.builtins import CustomForm  # noqa: E402
from calm.dsl.builtins.models.runbook_service import (  # noqa: E402
    _runbook_service_create,
)


class TestRunbookCustomForm:
    def test_runbook_service_lazy_form_auto_resolves_form_name_yaml(
        self, tmp_path, stub_calm_version, monkeypatch
    ):
        # Filename embeds the form name: specs/runbook_<form_name>.yaml.
        (tmp_path / "specs").mkdir()
        (tmp_path / "specs" / "runbook_rb_form.yaml").write_text(
            synth_custom_form_yaml("rb_form")
        )
        monkeypatch.chdir(tmp_path)

        rb = _runbook_service_create(custom_form=CustomForm(name="rb_form"))
        cdict = rb.compile()
        assert cdict["use_custom_form"] is False
        assert len(cdict["custom_form_definition_list"]) == 1
        assert cdict["custom_form_definition_list"][0]["name"] == "rb_form"

    def test_runbook_service_explicit_form_does_not_read_yaml(
        self, tmp_path, stub_calm_version, monkeypatch
    ):
        (tmp_path / "specs").mkdir()
        (tmp_path / "specs" / "runbook_from_disk.yaml").write_text(
            synth_custom_form_yaml("from_disk")
        )
        monkeypatch.chdir(tmp_path)

        rb = _runbook_service_create(
            custom_form=CustomForm(
                name="from_inline",
                spec={"description": "inline only", "resources": {"schema": {}}},
            )
        )
        cdict = rb.compile()
        assert cdict["custom_form_definition_list"][0]["name"] == "from_inline"

    def test_runbook_service_use_custom_form_true_retained(self, stub_calm_version):
        rb = _runbook_service_create(use_custom_form=True)
        cdict = rb.compile()
        assert cdict["use_custom_form"] is True

    def test_runbook_service_synthesises_reference(
        self, tmp_path, stub_calm_version, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)

        rb = _runbook_service_create(
            custom_form=CustomForm(
                name="rb_explicit", resources={"schema": {}, "type": "USER"}
            )
        )
        cdict = rb.compile()
        ref = cdict["custom_form_reference"]
        assert ref["kind"] == "custom_form"
        assert ref["name"] == "rb_explicit"
        assert ref["uuid"] == cdict["custom_form_definition_list"][0]["uuid"]

    def test_runbook_service_no_form_keeps_payload_clean(self, stub_calm_version):
        rb = _runbook_service_create()
        cdict = rb.compile()
        assert cdict["use_custom_form"] is False
        assert "custom_form_definition_list" not in cdict
        assert "custom_form_reference" not in cdict


class TestRunbookNamespaceExports:
    def test_calm_dsl_runbooks_re_exports_custom_form(self):
        import calm.dsl.runbooks as rb_ns

        assert "CustomForm" in rb_ns.__all__
        assert "read_spec" in rb_ns.__all__


class TestRunbookSeedFixture:
    """End-to-end: rb_cf seed module loads, runbook compiles with form attached."""

    def _load_rb(self, target_dir):
        import importlib.util
        import os
        import shutil
        import sys
        import uuid

        seed = Path(__file__).resolve().parent.parent / "fixtures" / "rb_cf_seed"
        if not seed.is_dir():
            pytest.skip("rb_cf_seed fixture missing")
        if (target_dir / "runbook.py").exists():
            shutil.rmtree(target_dir)
        shutil.copytree(seed, target_dir)

        os.chdir(target_dir)
        mod_name = "_eng924013_rb_{}".format(uuid.uuid4().hex[:8])
        spec = importlib.util.spec_from_file_location(
            mod_name, str(target_dir / "runbook.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_seed_runbook_compiles_with_custom_form(self, tmp_path, stub_calm_version):
        mod = self._load_rb(tmp_path / "rb_cf")
        rs = mod.DslRunbook.runbook
        cdict = rs.compile()
        assert cdict["use_custom_form"] is False
        assert len(cdict["custom_form_definition_list"]) == 1
        cf = cdict["custom_form_definition_list"][0]
        assert cf["name"] == "rb_cf_form"
        assert "branch" in cf["resources"]["schema"]

    def test_seed_runbook_synthesises_reference(self, tmp_path, stub_calm_version):
        mod = self._load_rb(tmp_path / "rb_cf")
        cdict = mod.DslRunbook.runbook.compile()
        ref = cdict["custom_form_reference"]
        assert ref["kind"] == "custom_form"
        assert ref["name"] == "rb_cf_form"
        assert ref["uuid"] == cdict["custom_form_definition_list"][0]["uuid"]
