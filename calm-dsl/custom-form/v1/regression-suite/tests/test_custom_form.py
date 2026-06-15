"""CustomForm ergonomic + auto-resolve + retention tests.

Covers:
* Lazy ``CustomForm(name=...)`` (no ``spec=``) auto-resolves to
  ``specs/<profile>_custom_form.yaml`` (or ``specs/runbook_custom_form.yaml``)
  at compile time.
* Explicit ``CustomForm(name=..., spec=...)`` still wins over the
  canonical file when both exist.
* Decompile re-emits the lazy form, never the verbose one.
* The compiled payload still preserves the form blob for round trip.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from helpers import compile_blueprint_payload, load_blueprint_module  # noqa: E402

from calm.dsl.builtins import CustomForm  # noqa: E402
from calm.dsl.builtins.models.custom_form import (  # noqa: E402
    load_custom_form_spec,
)


# ---------------------------------------------------------------------------
# Ergonomic: lazy CustomForm(name=...)
# ---------------------------------------------------------------------------


class TestCustomFormErgonomic:
    def test_lazy_factory_marks_auto_resolve(self, stub_calm_version):
        cf = CustomForm(name="LazyForm")
        assert getattr(cf, "__cf_auto_resolve__", False) is True

    def test_explicit_spec_disables_auto_resolve(self, stub_calm_version):
        cf = CustomForm(
            name="ExplicitForm",
            spec={"resources": {"schema": {}}, "description": "demo"},
        )
        assert getattr(cf, "__cf_auto_resolve__", True) is False

    def test_explicit_resources_disables_auto_resolve(self, stub_calm_version):
        cf = CustomForm(name="F", resources={"schema": {}})
        assert getattr(cf, "__cf_auto_resolve__", True) is False

    def test_explicit_description_disables_auto_resolve(self, stub_calm_version):
        cf = CustomForm(name="F", description="some desc")
        assert getattr(cf, "__cf_auto_resolve__", True) is False


class TestCustomFormAutoResolve:
    def _write_yaml(self, dirpath: Path, yaml_filename: str, body: str = None):
        specs = dirpath / "specs"
        specs.mkdir(parents=True, exist_ok=True)
        body = body or (
            "name: from_yaml\n"
            "description: pulled from disk\n"
            "resources:\n"
            "  type: USER\n"
            "  schema: {}\n"
            "  uischema: {type: VerticalLayout, elements: []}\n"
        )
        (specs / yaml_filename).write_text(body)

    def test_lazy_form_pulls_from_canonical_yaml(
        self, tmp_path, stub_calm_version, monkeypatch
    ):
        self._write_yaml(tmp_path, "MyProfile_custom_form.yaml")
        monkeypatch.chdir(tmp_path)

        cf = CustomForm(name="MyForm")
        loaded = load_custom_form_spec(cf, "MyProfile_custom_form.yaml")
        assert loaded.get_dict()["description"] == "pulled from disk"

    def test_lazy_form_no_yaml_hard_errors(
        self, tmp_path, stub_calm_version, monkeypatch
    ):
        """Auto-resolve without a YAML on disk now aborts with a clear
        error rather than silently shipping empty resources (which used
        to surface as a misleading 422 from the server)."""

        monkeypatch.chdir(tmp_path)

        cf = CustomForm(name="MyForm")
        with pytest.raises(SystemExit) as exc:
            load_custom_form_spec(cf, "MyProfile_custom_form.yaml")
        assert "MyProfile_custom_form.yaml" in str(exc.value)

    def test_explicit_spec_skips_auto_resolve(
        self, tmp_path, stub_calm_version, monkeypatch
    ):
        self._write_yaml(tmp_path, "MyProfile_custom_form.yaml")
        monkeypatch.chdir(tmp_path)

        cf = CustomForm(
            name="MyForm",
            spec={"resources": {"schema": {"explicit": True}}},
        )
        loaded = load_custom_form_spec(cf, "MyProfile_custom_form.yaml")
        assert loaded.get_dict()["resources"]["schema"]

    def test_resolver_handles_none_input(self):
        assert load_custom_form_spec(None, "anything.yaml") is None


# ---------------------------------------------------------------------------
# bp_cf seed -- end-to-end compile of the lazy form
# ---------------------------------------------------------------------------


class TestCustomFormBpCfSeed:
    def test_seed_bp_compiles_lazy_form(self, bp_workdir):
        # Rewrite the bp_cf blueprint.py to use the lazy form (in case the
        # seed still has the verbose version) -- this test must work
        # against either shape.
        bp_path = bp_workdir / "blueprint.py"
        text = bp_path.read_text()
        # Idempotent rewrite from verbose to lazy.
        if "spec=read_spec" in text:
            text = (
                text.replace(
                    'spec=read_spec(os.path.join("specs", "Default_custom_form.yaml")),\n        ',
                    "",
                )
                .replace(
                    "CustomForm(\n        name=",
                    "CustomForm(name=",
                )
                .replace(
                    ",\n    )\n    use_custom_form",
                    ")\n    use_custom_form",
                )
            )
            bp_path.write_text(text)

        bp = load_blueprint_module(bp_path)
        payload = compile_blueprint_payload(bp)
        profiles = payload["spec"]["resources"]["app_profile_list"]
        assert profiles
        prof = profiles[0]
        assert prof["use_custom_form"] is False
        assert len(prof["custom_form_definition_list"]) == 1
        cf = prof["custom_form_definition_list"][0]
        assert cf["name"].startswith("custom_form_")
        # Resources came from the canonical specs yaml.
        assert "schema" in cf["resources"]
        assert "uischema" in cf["resources"]


# ---------------------------------------------------------------------------
# Decompile rendering -- emits lazy form text, never verbose
# ---------------------------------------------------------------------------


class TestCustomFormDecompileRendering:
    def test_render_emits_lazy_text(self, tmp_path):
        from calm.dsl.decompile import file_handler
        from calm.dsl.decompile.custom_form import render_custom_form_blob

        bp_dir = tmp_path / "bp"
        file_handler.init_bp_dir(str(bp_dir))

        text = render_custom_form_blob(
            yaml_filename="MyProfile_custom_form.yaml",
            blob={
                "name": "MyForm",
                "description": "x",
                "resources": {
                    "schema": '{"a":1}',
                    "uischema": "{}",
                    "type": "USER",
                },
            },
        )
        assert text == 'CustomForm(name="MyForm")'

    def test_render_writes_canonical_yaml(self, tmp_path):
        from calm.dsl.decompile import file_handler
        from calm.dsl.decompile.custom_form import render_custom_form_blob

        bp_dir = tmp_path / "bp"
        file_handler.init_bp_dir(str(bp_dir))

        render_custom_form_blob(
            yaml_filename="MyProfile_custom_form.yaml",
            blob={
                "name": "MyForm",
                "description": "x",
                "resources": {
                    "schema": '{"a":1}',
                    "uischema": "{}",
                    "type": "USER",
                },
            },
        )
        assert (bp_dir / "specs" / "MyProfile_custom_form.yaml").is_file()
