"""Round-trip diff tests.

Covers the ``compile -> serialize -> recompile`` and
``decompile-render -> auto-resolve -> compile`` round trips. Uses
``deepdiff`` (already a calm-dsl dep) so newly-introduced shape drift
is caught automatically.

Tests in this file: 10.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from helpers import (  # noqa: E402
    compile_blueprint_payload,
    load_blueprint_module,
    synth_custom_form_yaml,
    synth_multi_profile_blueprint,
)


try:
    from deepdiff import DeepDiff
except ImportError:  # pragma: no cover
    DeepDiff = None


@pytest.fixture
def stable_multi_bp(tmp_path, stub_calm_version):
    bp_dir = tmp_path / "stable_bp"
    bp_dir.mkdir()
    (bp_dir / "blueprint.py").write_text(synth_multi_profile_blueprint(2))
    (bp_dir / "specs").mkdir()
    for i in range(2):
        (bp_dir / "specs" / "Profile{i}_cf_p{i}.yaml".format(i=i)).write_text(
            synth_custom_form_yaml(name="cf_p{}".format(i))
        )
    return bp_dir


# ---------------------------------------------------------------------------
# Idempotent compile
# ---------------------------------------------------------------------------


class TestRoundTripIdempotent:
    def test_compile_twice_produces_identical_payload(self, stable_multi_bp):
        bp = load_blueprint_module(stable_multi_bp / "blueprint.py")
        a = compile_blueprint_payload(bp)
        b = compile_blueprint_payload(bp)
        if DeepDiff is None:
            assert a == b
        else:
            assert DeepDiff(a, b, ignore_order=True) == {}

    def test_form_definition_list_keeps_size_after_repeat_compile(
        self, stable_multi_bp
    ):
        bp = load_blueprint_module(stable_multi_bp / "blueprint.py")
        compile_blueprint_payload(bp)
        payload = compile_blueprint_payload(bp)
        for prof in payload["spec"]["resources"]["app_profile_list"]:
            assert len(prof["custom_form_definition_list"]) == 1


# ---------------------------------------------------------------------------
# Yaml drift detection
# ---------------------------------------------------------------------------


class TestRoundTripYamlDrift:
    def test_edit_yaml_affects_next_compile(self, stable_multi_bp):
        # Compile once.
        bp = load_blueprint_module(stable_multi_bp / "blueprint.py")
        before = compile_blueprint_payload(bp)
        before_desc = before["spec"]["resources"]["app_profile_list"][0][
            "custom_form_definition_list"
        ][0]["description"]

        # Edit the canonical yaml.
        yaml_path = stable_multi_bp / "specs" / "Profile0_cf_p0.yaml"
        text = yaml_path.read_text().replace("regression seed", "edited description")
        yaml_path.write_text(text)

        # Reload + recompile -- description must reflect the edit.
        bp = load_blueprint_module(stable_multi_bp / "blueprint.py")
        after = compile_blueprint_payload(bp)
        after_desc = after["spec"]["resources"]["app_profile_list"][0][
            "custom_form_definition_list"
        ][0]["description"]

        assert before_desc == "regression seed"
        assert after_desc == "edited description"


# ---------------------------------------------------------------------------
# CustomForm schema/uischema stringification round-trip
# ---------------------------------------------------------------------------


class TestRoundTripStringification:
    def test_schema_compiles_to_json_string(self, stable_multi_bp):
        bp = load_blueprint_module(stable_multi_bp / "blueprint.py")
        payload = compile_blueprint_payload(bp)
        prof = payload["spec"]["resources"]["app_profile_list"][0]
        cf = prof["custom_form_definition_list"][0]
        assert isinstance(cf["resources"]["schema"], str)
        # Empty dict in yaml -> "{}" JSON string.
        assert json.loads(cf["resources"]["schema"]) == {}

    def test_uischema_compiles_to_json_string(self, stable_multi_bp):
        bp = load_blueprint_module(stable_multi_bp / "blueprint.py")
        payload = compile_blueprint_payload(bp)
        prof = payload["spec"]["resources"]["app_profile_list"][0]
        cf = prof["custom_form_definition_list"][0]
        assert isinstance(cf["resources"]["uischema"], str)
        ui = json.loads(cf["resources"]["uischema"])
        assert ui["type"] == "VerticalLayout"


# ---------------------------------------------------------------------------
# Compile shape contract -- top-level keys
# ---------------------------------------------------------------------------


class TestRoundTripShape:
    def test_profile_payload_has_all_expected_cf_keys(self, stable_multi_bp):
        bp = load_blueprint_module(stable_multi_bp / "blueprint.py")
        payload = compile_blueprint_payload(bp)
        prof = payload["spec"]["resources"]["app_profile_list"][0]
        # All three keys present and well-formed.
        assert "use_custom_form" in prof
        assert "custom_form_reference" in prof
        assert "custom_form_definition_list" in prof
        assert isinstance(prof["custom_form_definition_list"], list)
        assert isinstance(prof["custom_form_reference"], dict)

    def test_form_resources_has_three_keys(self, stable_multi_bp):
        bp = load_blueprint_module(stable_multi_bp / "blueprint.py")
        payload = compile_blueprint_payload(bp)
        cf = payload["spec"]["resources"]["app_profile_list"][0][
            "custom_form_definition_list"
        ][0]
        assert set(cf["resources"].keys()) >= {"schema", "uischema", "type"}

    def test_form_type_defaults_to_user(self, stable_multi_bp):
        """``CUSTOM_FORM_DEFAULT_TYPE`` is ``USER`` (the legacy
        ``jsonforms`` placeholder is not in the server enum and would
        be rejected with a 422)."""

        bp = load_blueprint_module(stable_multi_bp / "blueprint.py")
        payload = compile_blueprint_payload(bp)
        cf = payload["spec"]["resources"]["app_profile_list"][0][
            "custom_form_definition_list"
        ][0]
        assert cf["resources"]["type"] == "USER"


# ---------------------------------------------------------------------------
# Decompile-render -> compile round trip
# ---------------------------------------------------------------------------


class TestRoundTripDecompileToCompile:
    def test_render_blob_then_auto_resolve_yields_same_resources(self, tmp_path):
        from calm.dsl.decompile import file_handler
        from calm.dsl.decompile.custom_form import render_custom_form_blob

        bp_dir = tmp_path / "bp_rt"
        file_handler.init_bp_dir(str(bp_dir))

        original_blob = {
            "name": "RtForm",
            "description": "rt-demo",
            "resources": {
                "schema": '{"prop": {"type": "string"}}',
                "uischema": '{"type": "VerticalLayout"}',
                "type": "USER",
            },
        }
        text = render_custom_form_blob(
            yaml_filename="MyProf_custom_form.yaml", blob=original_blob
        )
        assert text == 'CustomForm(name="RtForm")'

        from calm.dsl.builtins import CustomForm
        from calm.dsl.builtins.models.custom_form import load_custom_form_spec
        import os

        prev = os.getcwd()
        os.chdir(bp_dir)
        try:
            cf = CustomForm(name="RtForm")
            resolved = load_custom_form_spec(cf, "MyProf_custom_form.yaml")
            cdict = resolved.get_dict()
        finally:
            os.chdir(prev)

        # The auto-resolved cdict carries the same logical content as
        # the original server blob, modulo the fact that the resources
        # we authored are dicts (not yet JSON-stringified) until compile.
        assert cdict["name"] == "RtForm"
        assert cdict["description"] == "rt-demo"
        # schema / uischema were JSON strings on the server; the yaml
        # writer parsed them to dicts; CustomForm.compile re-stringifies.
        assert json.loads(cdict["resources"]["schema"]) == {"prop": {"type": "string"}}
        assert json.loads(cdict["resources"]["uischema"]) == {"type": "VerticalLayout"}
