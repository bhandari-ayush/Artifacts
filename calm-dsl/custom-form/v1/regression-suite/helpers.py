"""Shared helpers for ENG-924013 regression tests.

Provides:
* DSL-import helpers that load a blueprint.py / runbook.py file as a
  fresh module (so each test gets a clean class registry).
* Mutation helpers -- inject @@{var}@@ macros into substrate / NIC / disk
  fields without monkey-patching the entire BP.
* Assertion helpers -- find a specific profile / NIC / disk in a
  compiled cdict by name.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import textwrap
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_blueprint_module(bp_py_path: Path):
    """Load *bp_py_path* as a uniquely-named module so repeat calls don't
    collide on Python's module cache. Returns the loaded module.

    Note: cwd is **not** restored on return -- callers should pair this
    with ``compile_blueprint_payload`` (which expects to run while the
    cwd is still the BP directory) or use the
    :func:`bp_workdir_chdir` context manager.
    """

    bp_py_path = Path(bp_py_path).resolve()
    # Set cwd so:
    #  * relative ``read_spec("specs/...")`` calls in the BP body resolve
    #    relative to the BP dir;
    #  * CustomForm auto-resolve (``specs/<owner>_custom_form.yaml``) finds
    #    the canonical file during a later compile().
    os.chdir(bp_py_path.parent)

    mod_name = "_eng924013_bp_{}".format(uuid.uuid4().hex[:8])
    spec = importlib.util.spec_from_file_location(mod_name, str(bp_py_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    # Stash the bp dir on the module so callers (and our compile helper)
    # can recover it. This survives tear-down.
    mod.__bp_dir__ = bp_py_path.parent
    return mod


class bp_workdir_chdir:
    """Context manager: ``with bp_workdir_chdir(bp_path): compile(...)``.

    Pushes cwd to the BP dir for the duration of the block; pops on exit.
    Tests that need to clean up should use this rather than
    ``load_blueprint_module`` directly.
    """

    def __init__(self, bp_py_path):
        self._target = Path(bp_py_path).resolve().parent

    def __enter__(self):
        self._prev = os.getcwd()
        os.chdir(self._target)
        return self._target

    def __exit__(self, *exc):
        os.chdir(self._prev)
        return False


def compile_profile_class(profile_cls):
    """Compile a Profile DSL class via cwd-aware loader.

    Returns the cdict the server would receive.
    """

    return profile_cls.compile()


def compile_blueprint_payload(bp_module):
    """Find the Blueprint class in *bp_module* and call ``create_blueprint_payload``.

    Returns the dict-shaped payload (``payload.get_dict()``).
    """

    from calm.dsl.builtins import (
        Blueprint,
        BlueprintType,
        create_blueprint_payload,
    )

    bp_cls = None
    for name in dir(bp_module):
        if name.startswith("__"):
            continue
        attr = getattr(bp_module, name)
        if isinstance(attr, BlueprintType) and attr is not Blueprint:
            bp_cls = attr
            break
    if bp_cls is None:
        raise RuntimeError("No Blueprint subclass found in {}".format(bp_module))

    payload, err = create_blueprint_payload(bp_cls)
    if err:
        raise RuntimeError("create_blueprint_payload failed: {}".format(err))
    return payload.get_dict()


def find_substrate(payload: Dict[str, Any], name: Optional[str] = None) -> Dict[str, Any]:
    """Return the first substrate (or one matching *name*) from a BP payload."""

    sd_list = payload["spec"]["resources"].get("substrate_definition_list", [])
    if not sd_list:
        raise AssertionError("No substrates in payload")
    if name is None:
        return sd_list[0]
    for sub in sd_list:
        if sub.get("name") == name:
            return sub
    raise AssertionError(
        "Substrate {} not found; available: {}".format(
            name, [s.get("name") for s in sd_list]
        )
    )


def get_substrate_provider_spec(substrate: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``substrate.create_spec.resources`` (the AHV resources block)."""

    return (
        substrate.get("create_spec", {}).get("resources", {})
        if substrate.get("create_spec")
        else {}
    )


def write_blueprint_with_macros(
    src_bp: Path,
    dest_bp: Path,
    *,
    nic_subnet_macro: Optional[str] = None,
    nic_vpc_macro: Optional[str] = None,
    nic_mac_macro: Optional[str] = None,
    nic_ip_macro: Optional[str] = None,
    nic_cluster_macro: Optional[str] = None,
    vm_name_macro: Optional[str] = None,
    cluster_macro: Optional[str] = None,
    memory_macro: Optional[str] = None,
):
    """Apply targeted macro substitutions to a copied blueprint.py.

    The NIC kwargs are special-cased: we *replace* the entire
    ``nics = [...]`` block with a freshly-rendered single-line call so
    we don't have to play balanced-paren tricks on the multi-line seed.
    Other substitutions are surgical replacements of known seed strings.
    """

    text = Path(src_bp).read_text()

    if cluster_macro:
        text = text.replace(
            '"auto_cluster_nested_69fc495b7298f69c60bd0524"',
            '"{}"'.format(cluster_macro),
        )

    if vm_name_macro:
        text = text.replace(
            'name = "vm-@@{calm_array_index}@@-@@{calm_time}@@"',
            'name = "{}"'.format(vm_name_macro),
        )

    if memory_macro:
        text = text.replace("memory = 1", 'memory = "{}"'.format(memory_macro))

    # NIC mutation: rewrite the whole ``nics = [ AhvVmNic.NormalNic.ingress(
    # ...) ]`` block in one shot so we don't have to balance parens. The
    # block in the seed bp_cf is exactly this multi-line form.
    if any(
        [
            nic_subnet_macro,
            nic_vpc_macro,
            nic_mac_macro,
            nic_ip_macro,
            nic_cluster_macro,
        ]
    ):
        subnet_arg = nic_subnet_macro or "vlan.0"
        kwargs_parts = []
        if nic_vpc_macro:
            kwargs_parts.append('vpc="{}"'.format(nic_vpc_macro))
        elif nic_cluster_macro:
            kwargs_parts.append('cluster="{}"'.format(nic_cluster_macro))
        if nic_mac_macro:
            kwargs_parts.append('mac_address="{}"'.format(nic_mac_macro))
        if nic_ip_macro:
            kwargs_parts.append('ip_endpoints=["{}"]'.format(nic_ip_macro))

        kwargs_str = ", " + ", ".join(kwargs_parts) if kwargs_parts else ""
        new_nics_block = (
            '    nics = [AhvVmNic.NormalNic.ingress("{subnet}"{kw})]'.format(
                subnet=subnet_arg, kw=kwargs_str
            )
        )

        # Match the existing nics block from "    nics = [" through the
        # matching "    ]" line.
        lines = text.splitlines()
        start = None
        end = None
        for i, line in enumerate(lines):
            if start is None and line.strip().startswith("nics = ["):
                start = i
                continue
            if start is not None and line.strip() == "]":
                end = i
                break
        if start is not None and end is not None:
            lines[start : end + 1] = [new_nics_block]
            text = "\n".join(lines) + "\n"

    Path(dest_bp).write_text(text)
    return dest_bp


JSON_MACRO_LITERAL = (
    "@@{my_json_var | json | replace('\\\"', '\\\\\"')}@@"
)
"""Shape used for JSON-bearing macros (per ENG-924013 plan §5.5)."""


def normal_macro(var_name: str = "my_var") -> str:
    """Standard scalar macro -- substitutable into any string field."""

    return "@@{{{}}}@@".format(var_name)


def synth_multi_profile_blueprint(num_profiles: int) -> str:
    """Generate a blueprint.py with N profiles, each owning its own CustomForm.

    Each profile auto-resolves to its canonical
    ``specs/Profile{i}_custom_form.yaml`` (via the ENG-924013 ergonomic).
    The generated file is intentionally minimal (one Service / Package /
    Substrate / Deployment shared across all profiles) so the test
    focuses on the multi-CustomForm contract.
    """

    profile_blocks = "\n\n".join(
        textwrap.dedent(
            """
            class Profile{idx}(Profile):
                deployments = [deployment_shared]
                custom_form = CustomForm(name="cf_p{idx}")
                use_custom_form = False
            """
        )
        .strip()
        .format(idx=i)
        for i in range(num_profiles)
    )

    profile_refs = ", ".join("Profile{}".format(i) for i in range(num_profiles))

    return textwrap.dedent(
        """
        from calm.dsl.builtins import *  # no_qa


        class SvcShared(Service):
            pass


        class PkgShared(Package):
            services = [ref(SvcShared)]


        class vm_resources(AhvVmResources):
            memory = 1
            vCPUs = 1
            cores_per_vCPU = 1


        class vm_provider(AhvVm):
            resources = vm_resources


        class SubShared(Substrate):
            account = Ref.Account("NTNX_LOCAL_AZ")
            os_type = "Linux"
            provider_type = "AHV_VM"
            provider_spec = vm_provider


        class deployment_shared(Deployment):
            min_replicas = "1"
            max_replicas = "1"
            default_replicas = "1"
            packages = [ref(PkgShared)]
            substrate = ref(SubShared)


        {profile_blocks}


        class MultiCfBp(Blueprint):
            services = [SvcShared]
            packages = [PkgShared]
            substrates = [SubShared]
            profiles = [{profile_refs}]
        """
    ).format(profile_blocks=profile_blocks, profile_refs=profile_refs)


def synth_custom_form_yaml(name: str, schema_str: str = "") -> str:
    """Minimal CustomForm YAML for the auto-resolve path.

    ``resources.type`` must be one of the server-accepted values
    (``USER``/``SYSTEM``); ``USER`` is the default for DSL-authored
    forms.
    """

    return textwrap.dedent(
        """
        name: {name}
        description: regression seed
        resources:
          type: USER
          schema: {schema_str}
          uischema:
            type: VerticalLayout
            elements: []
        """
    ).format(name=name, schema_str=schema_str or "{}")
