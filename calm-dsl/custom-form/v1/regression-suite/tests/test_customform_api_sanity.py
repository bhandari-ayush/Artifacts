"""CustomFormAPI sanity coverage.

Confirms two contractual properties of the read-only client:

* The two GET-style paths -- ``read(uuid)`` and ``list(params)`` --
  reach the underlying connection. The DSL itself does not call these,
  but external tools (introspection scripts, the dashboard UI, etc.)
  rely on them, so a regression that breaks routing or
  ``resource_type`` would be silent without this check.
* The three write paths (``create`` / ``update`` / ``delete``) raise
  ``NotImplementedError`` so any code path that tries to mutate a form
  via REST surfaces immediately instead of issuing a request the server
  may or may not reject.

Mocks the connection + resolver the same way ``tests/unit/api`` does
in-tree.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calm.dsl.api.connection import Connection  # noqa: E402
from calm.dsl.api.custom_form import CustomFormAPI  # noqa: E402
from calm.dsl.api.resource import ResourceAPI  # noqa: E402


@pytest.fixture
def stub_api():
    """Build a CustomFormAPI wired to a mock Connection + mock resolver."""

    connection = Mock(spec=Connection)
    connection.host = "mock-host"
    connection._call.return_value = ({"status": {"name": "stub"}}, None)

    with patch("calm.dsl.api.resource.APIConnectivityDetailsResolver") as resolver_cls:
        resolver_cls.return_value.resolve.return_value = MagicMock(
            connection=connection, api_path="api/nutanix/v3/custom_forms"
        )
        api = CustomFormAPI(connection)

    return api, connection


class TestCustomFormApiReadPaths:
    def test_read_uses_resource_uuid_path(self, stub_api):
        api, connection = stub_api

        api.read("form-uuid-123")

        called_url = connection._call.call_args[0][0]
        assert called_url.endswith("/custom_forms/form-uuid-123")

    def test_list_uses_resource_list_path(self, stub_api):
        api, connection = stub_api

        api.list({"length": 20})

        called_url = connection._call.call_args[0][0]
        assert called_url.endswith("/custom_forms/list")

    def test_inherits_from_resource_api(self):
        assert issubclass(CustomFormAPI, ResourceAPI)


class TestCustomFormApiWritePathsAreDisabled:
    """Frozen policy P6 -- DSL never mutates a custom form via REST."""

    @pytest.mark.parametrize("method", ["create", "update", "delete"])
    def test_write_method_raises_not_implemented(self, stub_api, method):
        api, _ = stub_api

        with pytest.raises(NotImplementedError) as exc_info:
            getattr(api, method)()

        assert "read-only" in str(exc_info.value).lower()

    @pytest.mark.parametrize("method", ["create", "update", "delete"])
    def test_write_method_does_not_hit_connection(self, stub_api, method):
        api, connection = stub_api

        with pytest.raises(NotImplementedError):
            getattr(api, method)()

        connection._call.assert_not_called()
