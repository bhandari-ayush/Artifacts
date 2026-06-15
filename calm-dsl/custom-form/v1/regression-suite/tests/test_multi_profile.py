"""Multi-profile CustomForm coverage.

Each Profile in a Blueprint may own its OWN CustomForm. The ergonomic
compile path must:

* Auto-resolve ``specs/Profile<i>_<form_name>.yaml`` per profile.
* Emit ``custom_form_definition_list[0]`` per profile (NOT shared).
* Retain the authored ``use_custom_form`` on every profile.

Tests in this file: 8.
"""

from __future__ import annotations

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


def _build_multi_profile_workdir(
    tmp_path: Path, num_profiles: int, with_yaml: bool = True
) -> Path:
    bp_dir = tmp_path / "multi_bp"
    bp_dir.mkdir()
    (bp_dir / "blueprint.py").write_text(synth_multi_profile_blueprint(num_profiles))

    if with_yaml:
        specs = bp_dir / "specs"
        specs.mkdir()
        for i in range(num_profiles):
            (specs / "Profile{i}_cf_p{i}.yaml".format(i=i)).write_text(
                synth_custom_form_yaml(name="cf_p{}".format(i))
            )
    return bp_dir


# ---------------------------------------------------------------------------
# Compile -- N profiles, N CustomForms
# ---------------------------------------------------------------------------


class TestMultiProfileCompile:
    @pytest.mark.parametrize("num_profiles", [2, 3, 5])
    def test_compile_populates_each_profile_form(
        self, tmp_path, num_profiles, stub_calm_version
    ):
        bp_dir = _build_multi_profile_workdir(tmp_path, num_profiles)
        bp = load_blueprint_module(bp_dir / "blueprint.py")
        payload = compile_blueprint_payload(bp)

        profiles = payload["spec"]["resources"]["app_profile_list"]
        assert len(profiles) == num_profiles
        for i, prof in enumerate(profiles):
            assert prof["use_custom_form"] is False
            assert len(prof["custom_form_definition_list"]) == 1
            assert prof["custom_form_definition_list"][0]["name"] == "cf_p{}".format(i)

    def test_each_profile_form_carries_distinct_resources(
        self, tmp_path, stub_calm_version
    ):
        bp_dir = _build_multi_profile_workdir(tmp_path, 3, with_yaml=False)
        # Override per-profile yaml so each carries a distinct schema.
        specs = bp_dir / "specs"
        specs.mkdir()
        for i in range(3):
            (specs / "Profile{i}_cf_p{i}.yaml".format(i=i)).write_text(
                synth_custom_form_yaml(
                    name="cf_p{}".format(i),
                    schema_str='{{"profile_idx": {}}}'.format(i),
                )
            )

        bp = load_blueprint_module(bp_dir / "blueprint.py")
        payload = compile_blueprint_payload(bp)

        profiles = payload["spec"]["resources"]["app_profile_list"]
        seen = set()
        for i, prof in enumerate(profiles):
            sch = prof["custom_form_definition_list"][0]["resources"]["schema"]
            seen.add(sch)
        # All three schemas are distinct strings.
        assert len(seen) == 3

    def test_missing_yaml_hard_errors(self, tmp_path, stub_calm_version):
        """Lazy ``CustomForm(name=...)`` requires its YAML on disk.

        Previously this silently shipped empty schema/uischema and the
        server rejected with a misleading 422. The contract is now an
        explicit compile-time abort that names the missing file.
        """

        bp_dir = _build_multi_profile_workdir(tmp_path, 2, with_yaml=False)
        bp = load_blueprint_module(bp_dir / "blueprint.py")
        with pytest.raises(SystemExit) as exc:
            compile_blueprint_payload(bp)
        msg = str(exc.value)
        assert "Profile0_cf_p0.yaml" in msg
        assert "spec=read_spec" in msg


# ---------------------------------------------------------------------------
# Reference shape
# ---------------------------------------------------------------------------


class TestMultiProfileReferenceShape:
    def test_each_profile_has_synthesised_reference(self, tmp_path, stub_calm_version):
        bp_dir = _build_multi_profile_workdir(tmp_path, 2)
        bp = load_blueprint_module(bp_dir / "blueprint.py")
        payload = compile_blueprint_payload(bp)
        for i, prof in enumerate(payload["spec"]["resources"]["app_profile_list"]):
            ref = prof.get("custom_form_reference")
            assert ref is not None
            assert ref["kind"] == "custom_form"
            assert ref["uuid"] == prof["custom_form_definition_list"][0]["uuid"]
            assert ref["name"] == "cf_p{}".format(i)

    def test_reference_name_matches_form_name(self, tmp_path, stub_calm_version):
        bp_dir = _build_multi_profile_workdir(tmp_path, 1)
        bp = load_blueprint_module(bp_dir / "blueprint.py")
        payload = compile_blueprint_payload(bp)
        prof = payload["spec"]["resources"]["app_profile_list"][0]
        assert (
            prof["custom_form_reference"]["name"]
            == prof["custom_form_definition_list"][0]["name"]
        )


# ---------------------------------------------------------------------------
# Negative path -- mixing forms / no-forms across profiles
# ---------------------------------------------------------------------------


class TestMultiProfileMixed:
    def test_some_profiles_with_form_others_without(self, tmp_path, stub_calm_version):
        # Generate a 3-profile BP, then surgically drop the form from
        # profile 1 by editing its source line.
        bp_dir = _build_multi_profile_workdir(tmp_path, 3)
        bp_py = bp_dir / "blueprint.py"
        text = bp_py.read_text()
        # Remove the custom_form line from Profile1 only.
        text = text.replace(
            'class Profile1(Profile):\n    deployments = [deployment_shared]\n    custom_form = CustomForm(name="cf_p1")\n    use_custom_form = False',
            "class Profile1(Profile):\n    deployments = [deployment_shared]",
        )
        bp_py.write_text(text)

        bp = load_blueprint_module(bp_py)
        payload = compile_blueprint_payload(bp)

        profiles = payload["spec"]["resources"]["app_profile_list"]
        assert len(profiles) == 3
        # Profile0 + Profile2 keep the form; Profile1 has empty list.
        names_with_form = [p for p in profiles if p.get("custom_form_definition_list")]
        assert len(names_with_form) == 2
