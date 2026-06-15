"""ENG-924013 follow-up behaviours.

Covers the changes layered on top of the original retention work:

* R1 -- the specs/ filename now embeds the form name
  (``<context>_<form>.yaml``) instead of a fixed ``<context>_custom_form``.
* R2 -- ``use_custom_form`` is retained as authored (no longer forced to
  False); launch only *warns* via ``CUSTOM_FORM_LAUNCH_NOT_SUPPORTED_WARNING``.
* R3 -- decompile drops a ``specs/<prefix>_custom_form_runtime_variable.json``
  in launch shape, and ``calm launch -f <file>.json`` consumes it
  (including for dynamic HTTP/EXEC variables).
* R5 -- ``CustomForm(spec_file=...)`` is the convenience form of
  ``spec=read_spec(...)``: resolves relative to the caller .py and turns
  off the lazy ``specs/`` auto-load.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calm.dsl.builtins import CustomForm  # noqa: E402
from calm.dsl.constants import (  # noqa: E402
    CUSTOM_FORM_LAUNCH_NOT_SUPPORTED_WARNING,
    RUNBOOK_CUSTOM_FORM_PREFIX,
    custom_form_yaml_filename,
)


# ---------------------------------------------------------------------------
# R1 -- form-name-bearing spec filename
# ---------------------------------------------------------------------------


class TestSpecFilename:
    def test_filename_embeds_form_name(self):
        assert custom_form_yaml_filename("Default", "MyForm") == "Default_MyForm.yaml"

    def test_runbook_prefix_is_runbook(self):
        assert (
            custom_form_yaml_filename(RUNBOOK_CUSTOM_FORM_PREFIX, "rb_form")
            == "runbook_rb_form.yaml"
        )

    def test_decompile_writes_form_named_yaml(self, tmp_path):
        from calm.dsl.decompile import file_handler
        from calm.dsl.decompile.custom_form import render_custom_form_from_payload

        bp_dir = tmp_path / "bp"
        file_handler.init_bp_dir(str(bp_dir))

        line = render_custom_form_from_payload(
            custom_form_definition_list=[
                {
                    "name": "PickerForm",
                    "description": "d",
                    "resources": {"schema": "{}", "uischema": "{}", "type": "USER"},
                }
            ],
            use_custom_form=False,
            context_prefix="Default",
        )
        assert line == 'CustomForm(name="PickerForm")'
        assert (bp_dir / "specs" / "Default_PickerForm.yaml").is_file()


# ---------------------------------------------------------------------------
# R2 -- use_custom_form retention + launch warning
# ---------------------------------------------------------------------------


class TestUseCustomFormRetention:
    def test_launch_warning_constant_is_non_empty(self):
        assert CUSTOM_FORM_LAUNCH_NOT_SUPPORTED_WARNING
        assert "default" in CUSTOM_FORM_LAUNCH_NOT_SUPPORTED_WARNING.lower()

    def test_decompile_retained_form_logs_retention(self, tmp_path, caplog):
        """``use_custom_form=True`` on the wire => the renderer preserves the
        blob and logs that launch will fall back to the default flow."""

        from calm.dsl.decompile import file_handler
        from calm.dsl.decompile.custom_form import render_custom_form_from_payload

        bp_dir = tmp_path / "bp_retain"
        file_handler.init_bp_dir(str(bp_dir))

        import logging

        with caplog.at_level(logging.WARNING):
            line = render_custom_form_from_payload(
                custom_form_definition_list=[
                    {
                        "name": "RetForm",
                        "resources": {"schema": "{}", "uischema": "{}"},
                    }
                ],
                use_custom_form=True,
                context_prefix="Default",
            )
        assert line == 'CustomForm(name="RetForm")'
        assert any("use_custom_form=True" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# R3 -- runtime-variable JSON generation + launch consumption
# ---------------------------------------------------------------------------


class _FakeVar:
    """Stand-in for a decompiled variable object (``.editables`` / ``.name``
    / ``.value``)."""

    def __init__(self, name, value, editable):
        self.name = name
        self.value = value
        self.editables = {"value": True} if editable else {}


class TestRuntimeVarJsonGeneration:
    def test_writes_only_editable_vars_in_launch_shape(self, tmp_path):
        from calm.dsl.decompile import file_handler
        from calm.dsl.decompile.custom_form import render_custom_form_runtime_vars

        bp_dir = tmp_path / "bp_rt"
        file_handler.init_bp_dir(str(bp_dir))

        path = render_custom_form_runtime_vars(
            file_prefix="Default",
            launch_context="Default",
            variables=[
                _FakeVar("editable_one", "v1", editable=True),
                _FakeVar("fixed_two", "v2", editable=False),
            ],
        )
        assert path is not None
        data = json.loads(Path(path).read_text())
        # Only the runtime-editable var survives, in {name, context, value}
        # launch shape.
        assert data == [
            {
                "name": "editable_one",
                "context": "Default",
                "value": {"value": "v1"},
            }
        ]

    def test_no_editable_vars_writes_nothing(self, tmp_path):
        from calm.dsl.decompile import file_handler
        from calm.dsl.decompile.custom_form import render_custom_form_runtime_vars

        file_handler.init_bp_dir(str(tmp_path / "bp_none"))
        path = render_custom_form_runtime_vars(
            file_prefix="Default",
            launch_context="Default",
            variables=[_FakeVar("fixed", "v", editable=False)],
        )
        assert path is None


class TestRuntimeVarLaunchConsumption:
    def test_bare_json_array_parses_as_variable_list(self, tmp_path):
        from calm.dsl.cli.bps import parse_launch_runtime_vars

        f = tmp_path / "rt.json"
        f.write_text(
            json.dumps([{"name": "v", "context": "Default", "value": {"value": "x"}}])
        )
        assert parse_launch_runtime_vars(str(f)) == [
            {"name": "v", "context": "Default", "value": {"value": "x"}}
        ]

    def test_keyed_json_object_parses_variable_list(self, tmp_path):
        from calm.dsl.cli.bps import parse_launch_runtime_vars

        f = tmp_path / "rt_keyed.json"
        f.write_text(
            json.dumps(
                {
                    "variable_list": [
                        {"name": "v", "context": "Default", "value": {"value": "x"}}
                    ],
                    "substrate_list": [],
                }
            )
        )
        assert parse_launch_runtime_vars(str(f))[0]["name"] == "v"

    def test_invalid_extension_aborts(self, tmp_path):
        from calm.dsl.cli.bps import parse_launch_runtime_vars

        f = tmp_path / "rt.txt"
        f.write_text("nope")
        with pytest.raises(SystemExit):
            parse_launch_runtime_vars(str(f))

    def test_dynamic_var_value_comes_from_file_not_network(self):
        """A dynamic (HTTP/EXEC) variable's value is taken straight from the
        launch-params file when present -- the dynamic-option fetch is
        short-circuited, so the JSON works for dynamic vars too."""

        from calm.dsl.cli.bps import get_variable_value

        dynamic_var = {
            "name": "dyn",
            "context": "Default.variable",
            "type": "HTTP_LOCAL",
            "value": {"value": ""},
        }
        launch_runtime_vars = [
            {"name": "dyn", "context": "Default", "value": {"value": "from-file"}}
        ]
        # bp_data is unused on the launch-params branch; pass an empty stub.
        assert get_variable_value(dynamic_var, {}, launch_runtime_vars) == "from-file"


class TestRuntimeVarEndToEnd:
    """Example of custom runtime-editable use: decompile writes the runtime
    JSON, then ``launch -f`` reads it back and fills both a plain and a
    dynamic variable without prompting."""

    def test_decompiled_json_drives_static_and_dynamic_launch(self, tmp_path):
        from calm.dsl.decompile import file_handler
        from calm.dsl.decompile.custom_form import render_custom_form_runtime_vars
        from calm.dsl.cli.bps import parse_launch_runtime_vars, get_variable_value

        bp_dir = tmp_path / "bp_e2e"
        file_handler.init_bp_dir(str(bp_dir))

        # 1. decompile side: emit specs/Default_custom_form_runtime_variable.json
        path = render_custom_form_runtime_vars(
            file_prefix="Default",
            launch_context="Default",
            variables=[
                _FakeVar("env_name", "prod", editable=True),
                _FakeVar("region", "us-west", editable=True),
            ],
        )
        assert path is not None and Path(path).is_file()

        # 2. launch side: parse the same file as a variable_list
        launch_runtime_vars = parse_launch_runtime_vars(path)
        assert {v["name"] for v in launch_runtime_vars} == {"env_name", "region"}

        # 3a. plain runtime var -> value from file
        static_var = {
            "name": "env_name",
            "context": "Default.variable",
            "type": "LOCAL",
            "value": {"value": ""},
        }
        assert get_variable_value(static_var, {}, launch_runtime_vars) == "prod"

        # 3b. dynamic (EXEC/HTTP) runtime var -> value from file, option fetch
        # is short-circuited (no network).
        dynamic_var = {
            "name": "region",
            "context": "Default.variable",
            "type": "EXEC_LOCAL",
            "value": {"value": ""},
        }
        assert get_variable_value(dynamic_var, {}, launch_runtime_vars) == "us-west"


# ---------------------------------------------------------------------------
# R5 -- CustomForm(spec_file=...) convenience form of spec=read_spec(...)
# ---------------------------------------------------------------------------


class TestSpecFileParam:
    def test_spec_file_reads_via_read_spec_and_disables_auto_resolve(
        self, monkeypatch, stub_calm_version
    ):
        import calm.dsl.builtins.models.provider_spec as ps

        captured = {}

        def fake_read_spec(filename, depth=1):
            captured["filename"], captured["depth"] = filename, depth
            return {"resources": {"type": "USER", "schema": {}}}

        monkeypatch.setattr(ps, "read_spec", fake_read_spec)

        cf = CustomForm(name="F", spec_file="forms/x.yaml")

        # Resolved relative to the caller .py (read_spec -> CustomForm ->
        # caller is depth 2) and the lazy specs/ auto-load is off.
        assert captured == {"filename": "forms/x.yaml", "depth": 2}
        assert getattr(cf, "__cf_auto_resolve__", True) is False
        assert cf.get_dict()["resources"]["type"] == "USER"
