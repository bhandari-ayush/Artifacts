"""ENG-924013 runbook CustomForm round-trip proof.

Mirrors the FIXED decompile flow: keep the existing ``client.runbook.read``
endpoint and, when the response carries only a ``custom_form_reference``
UUID (the documented behaviour of ``runbook_resources_def_status`` --
the non-download schema gates ``custom_form_definition_list`` behind
``{% if download %}``), GET the form blob from ``client.custom_form.read``
and splice it into ``custom_form_definition_list`` so the rest of the
decompile (``render_custom_form_blob`` -> ``specs/runbook_custom_form.yaml``)
works unchanged.

Steps:
1. Load the seed runbook (``fixtures/rb_cf_seed/runbook.py``) and compile
   its ``RunbookService`` -> a cdict that already carries the embedded
   ``custom_form_definition_list`` (because the DSL compile populates it
   from ``specs/runbook_custom_form.yaml``).
2. Strip ``custom_form_definition_list`` and keep only a
   ``custom_form_reference`` (the shape ``GET /runbooks/{uuid}`` actually
   returns) -- this is what the buggy ENG-924013 path was tripping on.
3. Synthesise a ``custom_form_intent_response`` for the corresponding GET
   on ``/custom_forms/{uuid}`` from the original blob.
4. Patch ``client.runbook.read`` + ``client.custom_form.read`` and call the
   FIXED ``decompile_runbook_from_server``; the hydration logic should
   splice the blob back in, then ``render_custom_form_blob`` writes
   ``specs/runbook_custom_form.yaml``.
5. Copy that yaml into ``fixtures/rb_cf_seed/specs/runbook_custom_form.yaml``.

Run from the calm-dsl venv:
    ~/Workspace/calm-dsl/venv/bin/python scripts/_rb_round_trip_e2e.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

REGRESSION_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REGRESSION_ROOT / "fixtures" / "rb_cf_seed"
FIXTURE_SPECS = FIXTURE / "specs"
RUNBOOK_PY = FIXTURE / "runbook.py"

sys.path.insert(0, str(REGRESSION_ROOT.parent / "calm-dsl"))


def _stub_calm_version():
    from calm.dsl.store.version import Version

    Version.get_version = staticmethod(lambda _key: "4.4.0")


def _load_seed_runbook():
    os.chdir(FIXTURE)
    mod_name = "_eng924013_rb_{}".format(uuid.uuid4().hex[:8])
    spec = importlib.util.spec_from_file_location(mod_name, str(RUNBOOK_PY))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _build_read_payload(rb_cdict):
    """Wrap a ``RunbookService.compile()`` cdict in the server's
    ``runbook_intent_response`` envelope (the NON-download shape -- what
    ``GET /runbooks/{uuid}`` actually returns).

    Strips ``custom_form_definition_list`` to mirror the gating in
    ``server/styx/yamls/apps/runbook.yaml`` (``{% if download %}``); a
    ``custom_form_reference`` with the form's UUID is all that survives.
    """

    rb_uuid = str(uuid.uuid4())
    resources = json.loads(json.dumps(rb_cdict))  # deep copy
    cf_list = resources.pop("custom_form_definition_list", []) or []
    cf_blob = cf_list[0] if cf_list else None
    if cf_blob:
        resources["custom_form_reference"] = {
            "kind": "custom_form",
            "name": cf_blob["name"],
            "uuid": cf_blob["uuid"],
        }
    payload = {
        "metadata": {
            "kind": "runbook",
            "uuid": rb_uuid,
            "name": "DslRunbook",
            "spec_version": 1,
            "categories": {},
            "owner_reference": {
                "kind": "user",
                "name": "admin",
                "uuid": str(uuid.uuid4()),
            },
            "project_reference": {
                "kind": "project",
                "name": "default",
                "uuid": str(uuid.uuid4()),
            },
        },
        "status": {
            "name": "DslRunbook",
            "description": "",
            "uuid": rb_uuid,
            "state": "ACTIVE",
            "resources": resources,
        },
    }
    return payload, cf_blob


def _build_custom_form_get_response(cf_blob):
    """Mirror ``GET /custom_forms/{uuid}`` -> ``custom_form_intent_response``."""

    return {
        "metadata": {
            "kind": "custom_form",
            "uuid": cf_blob["uuid"],
            "name": cf_blob["name"],
        },
        "status": {
            "name": cf_blob["name"],
            "uuid": cf_blob["uuid"],
            "description": cf_blob.get("description", ""),
            "resources": cf_blob.get("resources", {}),
        },
        "spec": {
            "name": cf_blob["name"],
            "description": cf_blob.get("description", ""),
            "resources": cf_blob.get("resources", {}),
        },
    }


def main():
    _stub_calm_version()

    print("[step 1] load seed runbook + compile RunbookService -> cdict")
    mod = _load_seed_runbook()
    # ``compile()`` leaves nested entities as classes; ``get_dict()`` does the
    # JSON round-trip so every nested entity becomes a plain dict (which is
    # what the server's REST response shape looks like).
    rb_cdict = mod.DslRunbook.runbook.get_dict()
    assert rb_cdict.get("custom_form_definition_list"), (
        "Seed runbook compile must populate custom_form_definition_list "
        "(otherwise the test is meaningless)."
    )
    print("        cf def_count = {}".format(len(rb_cdict["custom_form_definition_list"])))
    print("        cf name      = {}".format(rb_cdict["custom_form_definition_list"][0]["name"]))

    # Sanitize: keep only the fields the server actually emits for a
    # ``RunbookService`` in the download response. We are not asserting
    # full server fidelity here -- just that the download payload carries
    # ``custom_form_definition_list`` and that decompile re-emits the YAML.
    # Replace embedded UUIDs with deterministic values for readability.

    print("[step 2] strip definition_list, keep only custom_form_reference")
    rb_read_payload, cf_blob = _build_read_payload(rb_cdict)
    assert cf_blob is not None, "Seed runbook must produce a custom-form blob"
    assert not rb_read_payload["status"]["resources"].get(
        "custom_form_definition_list"
    ), (
        "Read payload must NOT carry custom_form_definition_list -- the very "
        "field the non-download schema gates behind ``{% if download %}``."
    )
    assert rb_read_payload["status"]["resources"].get("custom_form_reference"), (
        "Read payload must carry custom_form_reference -- the pointer the "
        "non-download schema does expose."
    )
    cf_get_payload = _build_custom_form_get_response(cf_blob)

    print("[step 3] patch runbook.read + custom_form.read + run fixed decompile")
    from calm.dsl.cli import runbooks as rb_cli

    fake_rb_res = MagicMock()
    fake_rb_res.json.return_value = rb_read_payload

    fake_cf_res = MagicMock()
    fake_cf_res.json.return_value = cf_get_payload

    list_shape = {
        "metadata": rb_read_payload["metadata"],
        "status": {"uuid": rb_read_payload["status"]["uuid"]},
    }

    out_dir = Path(tempfile.mkdtemp(prefix="eng924013_rb_decompile_"))
    try:
        with patch.object(rb_cli, "get_api_client") as mock_get_client, patch.object(
            rb_cli, "get_runbook", return_value=list_shape
        ):
            client = MagicMock()
            client.runbook.read.return_value = (fake_rb_res, None)
            client.custom_form.read.return_value = (fake_cf_res, None)
            mock_get_client.return_value = client

            rb_cli.decompile_runbook_from_server(
                name="DslRunbook",
                runbook_dir=str(out_dir),
                prefix="",
                no_format=True,
            )

            assert client.runbook.read.called, (
                "REGRESSION: decompile_runbook_from_server skipped the "
                "existing runbook.read endpoint."
            )
            client.custom_form.read.assert_called_once_with(cf_blob["uuid"]), (
                "REGRESSION: decompile_runbook_from_server did not GET the "
                "custom_form for the reference UUID, so the form blob is lost."
            )

        produced_yaml = out_dir / "specs" / "runbook_custom_form.yaml"
        assert produced_yaml.is_file(), (
            "Fixed decompile did NOT write specs/runbook_custom_form.yaml; "
            "produced: {}".format(list((out_dir / "specs").iterdir()))
        )
        produced_text = produced_yaml.read_text()
        print("        produced specs/runbook_custom_form.yaml:")
        for line in produced_text.splitlines():
            print("            {}".format(line))

        rb_py = (out_dir / "runbook.py").read_text()
        assert 'CustomForm(name="rb_cf_form")' in rb_py, (
            "Fixed decompile DSL missing the CustomForm line"
        )
        assert ".runbook.custom_form = " in rb_py
        assert ".runbook.use_custom_form = False" in rb_py
        print("[step 4] copy produced yaml -> fixture path")
        FIXTURE_SPECS.mkdir(parents=True, exist_ok=True)
        target = FIXTURE_SPECS / "runbook_custom_form.yaml"
        shutil.copyfile(produced_yaml, target)
        print("        wrote {}".format(target))
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)

    print("\n[ALL GREEN] runbook CustomForm now survives decompile.")


if __name__ == "__main__":
    main()
