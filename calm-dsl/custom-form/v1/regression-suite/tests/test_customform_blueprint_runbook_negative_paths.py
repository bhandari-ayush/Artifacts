"""Negative-path coverage for CustomForm on Profile (BP) and RunbookService."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calm.dsl.builtins import CustomForm  # noqa: E402
from calm.dsl.builtins.models.profile import profile as profile_factory  # noqa: E402
from calm.dsl.builtins.models.runbook_service import (  # noqa: E402
    _runbook_service_create,
)
from calm.dsl.constants import (  # noqa: E402
    CUSTOM_FORM_LAUNCH_NOT_SUPPORTED_WARNING,
)


class TestUseCustomFormTrueRetained:
    """ENG-924013 follow-up: True is retained (not aborted); launch warns."""

    def test_profile_compile_retains_true(self):
        cdict = profile_factory(name="P1", use_custom_form=True).compile()
        assert cdict["use_custom_form"] is True

    def test_profile_compile_retains_true_with_form(self, stub_calm_version):
        cdict = profile_factory(
            name="P1",
            custom_form=CustomForm(name="X", resources={"schema": {}}),
            use_custom_form=True,
        ).compile()
        assert cdict["use_custom_form"] is True
        assert cdict["custom_form_definition_list"][0]["name"] == "X"

    def test_runbook_service_compile_retains_true(self):
        cdict = _runbook_service_create(use_custom_form=True).compile()
        assert cdict["use_custom_form"] is True

    def test_launch_warning_message_mentions_default_flow(self):
        assert "default" in CUSTOM_FORM_LAUNCH_NOT_SUPPORTED_WARNING.lower()
        assert "not supported" in CUSTOM_FORM_LAUNCH_NOT_SUPPORTED_WARNING.lower()


class TestCustomFormApiIsReadOnly:
    """The DSL must not author custom forms via the API client."""

    def test_create_raises_not_implemented(self):
        from calm.dsl.api.custom_form import CustomFormAPI

        api = CustomFormAPI.__new__(CustomFormAPI)
        with pytest.raises(NotImplementedError):
            api.create()

    def test_update_raises_not_implemented(self):
        from calm.dsl.api.custom_form import CustomFormAPI

        api = CustomFormAPI.__new__(CustomFormAPI)
        with pytest.raises(NotImplementedError):
            api.update()

    def test_delete_raises_not_implemented(self):
        from calm.dsl.api.custom_form import CustomFormAPI

        api = CustomFormAPI.__new__(CustomFormAPI)
        with pytest.raises(NotImplementedError):
            api.delete()
