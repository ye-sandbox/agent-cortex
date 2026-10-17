"""Hermetic tests for cortex config CLI sub-commands."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cortex.cli import app
from cortex.config.loader import CortexConfig, save_config

runner = CliRunner()


def test_cli_config_show_defaults(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    config_file = tmp_path / "config.yaml"
    save_config(cfg, config_file)

    # Human table output
    res = runner.invoke(app, ["config", "show", "--config", str(config_file)])
    assert res.exit_code == 0
    assert "Configuration for Tenant: default" in res.stdout
    assert "balanced" in res.stdout

    # JSON output
    res_json = runner.invoke(app, ["config", "show", "--config", str(config_file), "--json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.stdout)
    assert data["tenant_id"] == "default"
    assert data["effective_config"]["profile"] == "balanced"
    assert data["has_dynamic_override"] is False


def test_cli_config_set_and_show(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    config_file = tmp_path / "config.yaml"
    save_config(cfg, config_file)

    # Set profile to high for tenant 'analyst'
    res = runner.invoke(
        app,
        [
            "config",
            "set",
            "profile",
            "high",
            "--tenant",
            "analyst",
            "--config",
            str(config_file),
            "--description",
            "High tier for deep analysis",
        ],
    )
    assert res.exit_code == 0
    assert "Updated profile = high for tenant 'analyst'" in res.stdout

    # Set nested retrieval limit
    res_limit = runner.invoke(
        app,
        [
            "config",
            "set",
            "retrieval.default_limit",
            "25",
            "--tenant",
            "analyst",
            "--config",
            str(config_file),
            "--json",
        ],
    )
    assert res_limit.exit_code == 0
    limit_data = json.loads(res_limit.stdout)
    assert limit_data["status"] == "ok"
    assert limit_data["config"]["retrieval"]["default_limit"] == 25

    # Verify via show --json
    res_show = runner.invoke(
        app,
        [
            "config",
            "show",
            "--tenant",
            "analyst",
            "--config",
            str(config_file),
            "--json",
        ],
    )
    assert res_show.exit_code == 0
    show_data = json.loads(res_show.stdout)
    assert show_data["effective_config"]["profile"] == "high"
    assert show_data["effective_config"]["retrieval"]["default_limit"] == 25
    assert show_data["has_dynamic_override"] is True


def test_cli_config_list_and_delete_tenants(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    config_file = tmp_path / "config.yaml"
    save_config(cfg, config_file)

    # Seed two tenants
    runner.invoke(
        app,
        [
            "config",
            "set",
            "profile",
            "low",
            "--tenant",
            "bot1",
            "--config",
            str(config_file),
        ],
    )
    runner.invoke(
        app,
        [
            "config",
            "set",
            "profile",
            "high",
            "--tenant",
            "bot2",
            "--config",
            str(config_file),
        ],
    )

    # List tenants in JSON
    res_list = runner.invoke(
        app, ["config", "list-tenants", "--config", str(config_file), "--json"]
    )
    assert res_list.exit_code == 0
    list_data = json.loads(res_list.stdout)
    assert list_data["total_tenants"] >= 2
    tenant_ids = [t["tenant_id"] for t in list_data["tenants"]]
    assert "bot1" in tenant_ids
    assert "bot2" in tenant_ids

    # Delete bot1
    res_del = runner.invoke(
        app,
        [
            "config",
            "delete",
            "--tenant",
            "bot1",
            "--config",
            str(config_file),
            "--json",
        ],
    )
    assert res_del.exit_code == 0
    del_data = json.loads(res_del.stdout)
    assert del_data["deleted"] is True

    # Deleting again returns not_found
    res_del2 = runner.invoke(
        app,
        [
            "config",
            "delete",
            "--tenant",
            "bot1",
            "--config",
            str(config_file),
            "--json",
        ],
    )
    assert res_del2.exit_code == 0
    del2_data = json.loads(res_del2.stdout)
    assert del2_data["deleted"] is False


def test_cli_config_migrate(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.profile = CortexConfig().profile  # balanced
    cfg.retrieval.default_limit = 18
    cfg.storage.data_dir = data_dir
    config_file = tmp_path / "config.yaml"
    save_config(cfg, config_file)

    # Migrate to default tenant in DB
    res_mig = runner.invoke(
        app,
        [
            "config",
            "migrate",
            "--tenant",
            "default",
            "--config",
            str(config_file),
            "--json",
        ],
    )
    assert res_mig.exit_code == 0
    mig_data = json.loads(res_mig.stdout)
    assert mig_data["status"] == "ok"
    assert mig_data["migrated"] is True

    # Migrate again without force skips
    res_mig_skip = runner.invoke(
        app,
        [
            "config",
            "migrate",
            "--tenant",
            "default",
            "--config",
            str(config_file),
            "--json",
        ],
    )
    assert res_mig_skip.exit_code == 0
    mig_skip_data = json.loads(res_mig_skip.stdout)
    assert mig_skip_data["migrated"] is False

    # Migrate with overwrite succeeds
    res_mig_overwrite = runner.invoke(
        app,
        [
            "config",
            "migrate",
            "--tenant",
            "default",
            "--overwrite",
            "--config",
            str(config_file),
            "--json",
        ],
    )
    assert res_mig_overwrite.exit_code == 0
    mig_over_data = json.loads(res_mig_overwrite.stdout)
    assert mig_over_data["migrated"] is True
