"""Connector registry and base class."""

from onlime.connectors.base import BaseConnector, ConnectorResult
from onlime.connectors.registry import get_connector, list_connectors, register

# Import connectors to trigger @register
import onlime.connectors.telegram  # noqa: F401
import onlime.connectors.gdrive  # noqa: F401
import onlime.connectors.slack  # noqa: F401
import onlime.connectors.kakao  # noqa: F401

__all__ = ["BaseConnector", "ConnectorResult", "get_connector", "list_connectors", "register"]
