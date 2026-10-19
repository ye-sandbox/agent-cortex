"""Unit tests for AST-based code signature and dependency extraction."""

from cortex.models.graph import DependencyEdgeType
from cortex.parsers.code.extractor import (
    GolangASTExtractor,
    PythonASTExtractor,
    TypeScriptASTExtractor,
    extract_code_ast,
)

PYTHON_SOURCE = """
import os
import sys as system
from pathlib import Path
from cortex.storage.manager import StorageManager, CompactionResult

class BaseService:
    def __init__(self, name: str) -> None:
        self.name = name

class DataService(BaseService):
    \"\"\"Service managing data storage.\"\"\"

    def fetch_records(self, limit: int = 10) -> list[str]:
        mgr = StorageManager()
        return mgr.get_technologies()

def run_pipeline() -> None:
    svc = DataService("pipeline")
    svc.fetch_records(20)
"""

TS_SOURCE = """
import { useState, useEffect } from 'react';
import type { QueryClient } from '@tanstack/react-query';
import * as utils from './utils';

export interface BaseConfig {
    env: string;
}

export interface AppConfig extends BaseConfig {
    port: number;
}

export type Theme = 'light' | 'dark';

export enum Status {
    ACTIVE = 'active',
    PENDING = 'pending',
}

export class ServiceWorker implements BaseConfig {
    env: string = 'prod';

    public start(): void {
        utils.initLogger();
    }
}

export function createWorker(): ServiceWorker {
    return new ServiceWorker();
}

export const fetchDeals = async () => {
    return await utils.fetchApi('/deals');
};
"""

GO_SOURCE = """
package main

import (
    "fmt"
    "net/http"
    gin "github.com/gin-gonic/gin"
)

type Config struct {
    Port int
}

type Service interface {
    Start() error
}

func NewConfig(port int) *Config {
    fmt.Println(port)
    return &Config{Port: port}
}

func (c *Config) GetPort() int {
    return c.Port
}
"""


def test_python_ast_extractor() -> None:
    extractor = PythonASTExtractor()
    sigs, deps = extractor.extract(PYTHON_SOURCE, repo="cortex", file_path="svc.py")

    # Check dependencies (imports, extends, calls)
    import_mods = [d.target_module for d in deps if d.edge_type == DependencyEdgeType.IMPORT]
    assert "os" in import_mods
    assert "sys" in import_mods
    assert "cortex.storage.manager" in import_mods

    extends = [d for d in deps if d.edge_type == DependencyEdgeType.EXTENDS]
    assert len(extends) >= 1
    assert any(e.target_symbol == "BaseService" for e in extends)

    calls = [d for d in deps if d.edge_type == DependencyEdgeType.CALL]
    assert any("fetch_records" in c.target_symbol for c in calls)

    # Check signatures
    identifiers = [s.identifier for s in sigs]
    assert "BaseService" in identifiers
    assert "DataService" in identifiers
    assert "DataService.fetch_records" in identifiers
    assert "run_pipeline" in identifiers

    data_svc = next(s for s in sigs if s.identifier == "DataService")
    assert "Service managing data storage" in data_svc.docstring


def test_typescript_ast_extractor() -> None:
    extractor = TypeScriptASTExtractor()
    sigs, deps = extractor.extract(TS_SOURCE, repo="web", file_path="src/index.ts")

    # Check dependencies
    imports = [d for d in deps if d.edge_type == DependencyEdgeType.IMPORT]
    target_mods = [d.target_module for d in imports]
    assert "react" in target_mods
    assert "@tanstack/react-query" in target_mods
    assert "./utils" in target_mods

    extends = [d for d in deps if d.edge_type == DependencyEdgeType.EXTENDS]
    assert any(e.target_symbol == "BaseConfig" for e in extends)

    implements = [d for d in deps if d.edge_type == DependencyEdgeType.IMPLEMENTS]
    assert any(i.target_symbol == "BaseConfig" for i in implements)

    # Check signatures
    sig_map = {s.identifier: s for s in sigs}
    assert "BaseConfig" in sig_map
    assert sig_map["BaseConfig"].kind == "interface"
    assert "AppConfig" in sig_map
    assert "Theme" in sig_map
    assert sig_map["Theme"].kind == "type"
    assert "Status" in sig_map
    assert sig_map["Status"].kind == "enum"
    assert "ServiceWorker" in sig_map
    assert "ServiceWorker.start" in sig_map
    assert "createWorker" in sig_map
    assert "fetchDeals" in sig_map


def test_golang_ast_extractor() -> None:
    extractor = GolangASTExtractor()
    sigs, deps = extractor.extract(GO_SOURCE, repo="backend", file_path="main.go")

    # Check dependencies
    imports = [d for d in deps if d.edge_type == DependencyEdgeType.IMPORT]
    import_paths = [d.target_module for d in imports]
    assert "fmt" in import_paths
    assert "net/http" in import_paths
    assert "github.com/gin-gonic/gin" in import_paths

    calls = [d for d in deps if d.edge_type == DependencyEdgeType.CALL]
    assert any("Println" in c.target_symbol for c in calls)

    # Check signatures
    sig_map = {s.identifier: s for s in sigs}
    assert "Config" in sig_map
    assert sig_map["Config"].kind == "struct"
    assert "Service" in sig_map
    assert sig_map["Service"].kind == "interface"
    assert "NewConfig" in sig_map
    assert "Config.GetPort" in sig_map


def test_extract_code_ast_dispatcher() -> None:
    py_sigs, py_deps = extract_code_ast("def foo(): pass", "r", "app.py")
    assert len(py_sigs) == 1
    assert py_sigs[0].identifier == "foo"

    ts_sigs, ts_deps = extract_code_ast("export const bar = () => {};", "r", "app.ts")
    assert len(ts_sigs) == 1
    assert ts_sigs[0].identifier == "bar"

    go_sigs, go_deps = extract_code_ast("package main\nfunc Baz() {}", "r", "app.go")
    assert len(go_sigs) == 1
    assert go_sigs[0].identifier == "Baz"

    # Unsupported extension returns empty lists
    other_sigs, other_deps = extract_code_ast("# README", "r", "README.md")
    assert other_sigs == []
    assert other_deps == []
