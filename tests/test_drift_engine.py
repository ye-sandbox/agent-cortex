"""Unit and integration tests for ContractDriftEngine."""

from pathlib import Path

import pytest

from cortex.models.drift import (
    ChangeKind,
    ContractType,
    DriftSeverity,
)
from cortex.models.graph import CodeSignature
from cortex.retrieval.drift import ContractDriftEngine
from cortex.storage.manager import StorageManager

OPENAPI_V1 = """
openapi: "3.0.0"
info:
  title: Test API
  version: "1.0.0"
paths:
  /deals:
    get:
      summary: List deals
      parameters:
        - name: limit
          in: query
          required: false
      responses:
        "200":
          description: OK
    post:
      summary: Create deal
      responses:
        "201":
          description: Created
  /deals/{id}:
    delete:
      summary: Delete deal
      responses:
        "204":
          description: Deleted
"""

OPENAPI_V2_BREAKING = """
openapi: "3.0.0"
info:
  title: Test API
  version: "2.0.0"
paths:
  /deals:
    get:
      summary: List deals
      deprecated: true
      parameters:
        - name: tenant_id
          in: query
          required: true
      responses:
        "200":
          description: OK
    post:
      summary: Create deal
      responses:
        "201":
          description: Created
"""

COMPOSE_V1 = """
version: "3.8"
services:
  web:
    image: python:3.14
    ports:
      - "8000:8000"
  worker:
    image: worker:latest
  redis:
    image: redis:7
    ports:
      - "6379:6379"
"""

COMPOSE_V2_BREAKING = """
version: "3.8"
services:
  web:
    image: python:3.14
    ports:
      - "8080:8080"
  worker:
    image: worker:latest
  analytics:
    image: analytics:latest
"""


@pytest.fixture
def drift_engine(tmp_path: Path) -> ContractDriftEngine:
    """Fixture providing a clean ContractDriftEngine."""
    storage = StorageManager(data_dir=tmp_path / "data")
    return ContractDriftEngine(storage_manager=storage)


def test_diff_openapi_breaking_changes(drift_engine: ContractDriftEngine) -> None:
    """Verify detection of deleted endpoints, new required params, and deprecations in OpenAPI."""
    alerts = drift_engine.diff_openapi(
        repo="test-repo",
        file_path="specs/openapi.yaml",
        old_content=OPENAPI_V1,
        new_content=OPENAPI_V2_BREAKING,
    )

    # 1. /deals/{id} DELETE removed -> HIGH
    deleted_alert = next((a for a in alerts if a.change_kind == ChangeKind.REMOVED), None)
    assert deleted_alert is not None
    assert deleted_alert.severity == DriftSeverity.HIGH
    assert deleted_alert.identifier == "DELETE /deals/{id}"
    assert deleted_alert.contract_type == ContractType.OPENAPI

    # 2. tenant_id required parameter added -> HIGH
    req_param_alert = next((a for a in alerts if "tenant_id" in a.summary), None)
    assert req_param_alert is not None
    assert req_param_alert.severity == DriftSeverity.HIGH
    assert req_param_alert.change_kind == ChangeKind.MODIFIED

    # 3. /deals GET marked deprecated -> MEDIUM
    dep_alert = next((a for a in alerts if a.change_kind == ChangeKind.DEPRECATED), None)
    assert dep_alert is not None
    assert dep_alert.severity == DriftSeverity.MEDIUM
    assert "GET /deals" in dep_alert.identifier


def test_diff_compose_breaking_changes(drift_engine: ContractDriftEngine) -> None:
    """Verify detection of deleted services and removed port bindings in Docker Compose."""
    alerts = drift_engine.diff_compose(
        repo="test-repo",
        file_path="compose.yaml",
        old_content=COMPOSE_V1,
        new_content=COMPOSE_V2_BREAKING,
    )

    # 1. redis service removed -> HIGH
    redis_alert = next((a for a in alerts if a.change_kind == ChangeKind.REMOVED), None)
    assert redis_alert is not None
    assert redis_alert.severity == DriftSeverity.HIGH
    assert redis_alert.identifier == "services.redis"

    # 2. Port 8000:8000 removed from web service -> HIGH
    port_alert = next((a for a in alerts if "8000:8000" in a.summary), None)
    assert port_alert is not None
    assert port_alert.severity == DriftSeverity.HIGH
    assert port_alert.identifier == "services.web"

    # 3. analytics service added -> INFO
    added_alert = next((a for a in alerts if a.change_kind == ChangeKind.ADDED), None)
    assert added_alert is not None
    assert added_alert.severity == DriftSeverity.INFO
    assert added_alert.identifier == "services.analytics"


def test_diff_signatures_breaking_changes(drift_engine: ContractDriftEngine) -> None:
    """Verify detection of deleted exported symbols and signature parameter changes."""
    old_sigs = [
        CodeSignature(
            id="test-repo:src/core.py:function:process_payment",
            repo="test-repo",
            file_path="src/core.py",
            language="python",
            kind="function",
            identifier="process_payment",
            signature="def process_payment(amount: float) -> bool:",
            line_start=10,
            line_end=15,
            exported=True,
        ),
        CodeSignature(
            id="test-repo:src/core.py:function:calculate_tax",
            repo="test-repo",
            file_path="src/core.py",
            language="python",
            kind="function",
            identifier="calculate_tax",
            signature="def calculate_tax(rate: float) -> float:",
            line_start=20,
            line_end=25,
            exported=True,
        ),
    ]

    new_sigs = [
        CodeSignature(
            id="test-repo:src/core.py:function:process_payment",
            repo="test-repo",
            file_path="src/core.py",
            language="python",
            kind="function",
            identifier="process_payment",
            # Added non-default parameter 'currency' -> Breaking!
            signature="def process_payment(amount: float, currency: str) -> bool:",
            line_start=10,
            line_end=16,
            exported=True,
        ),
        # calculate_tax was deleted!
        CodeSignature(
            id="test-repo:src/core.py:function:refund",
            repo="test-repo",
            file_path="src/core.py",
            language="python",
            kind="function",
            identifier="refund",
            signature="def refund(tx_id: str) -> bool:",
            line_start=30,
            line_end=35,
            exported=True,
        ),
    ]

    alerts = drift_engine.diff_signatures(
        repo="test-repo",
        file_path="src/core.py",
        old_signatures=old_sigs,
        new_signatures=new_sigs,
    )

    # 1. calculate_tax removed -> HIGH
    deleted_sig = next((a for a in alerts if a.identifier == "calculate_tax"), None)
    assert deleted_sig is not None
    assert deleted_sig.change_kind == ChangeKind.REMOVED
    assert deleted_sig.severity == DriftSeverity.HIGH

    # 2. process_payment modified breakingly -> HIGH
    modified_sig = next((a for a in alerts if a.identifier == "process_payment"), None)
    assert modified_sig is not None
    assert modified_sig.change_kind == ChangeKind.MODIFIED
    assert modified_sig.severity == DriftSeverity.HIGH

    # 3. refund added -> INFO
    added_sig = next((a for a in alerts if a.identifier == "refund"), None)
    assert added_sig is not None
    assert added_sig.change_kind == ChangeKind.ADDED
    assert added_sig.severity == DriftSeverity.INFO
