"""Unit tests for Code AST contract parsers (Python, TypeScript, Go)."""

from cortex.models.chunk import ChunkCategory, ChunkLifecycle, ChunkScope
from cortex.parsers import (
    GoContractParser,
    PythonContractParser,
    TypeScriptContractParser,
    get_parser_for_file,
    parse_document,
)


class TestPythonContractParser:
    def test_parse_class_with_methods_and_docstrings(self) -> None:
        content = '''"""Module docstring."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ServiceClient(BaseClient, ABC):
    """High-performance API client for upstream cluster."""

    endpoint: str
    timeout: float = 10.0

    async def fetch_user(self, user_id: str) -> dict[str, str]:
        """Fetch remote user profile."""
        return {"id": user_id}

    @abstractmethod
    def health_check(self) -> bool:
        """Verify upstream reachability."""
        ...

    def _private_helper(self) -> None:
        pass

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
'''
        parser = PythonContractParser()
        chunks = parser.parse(
            content=content,
            repo="agent-cortex",
            file_path="src/cortex/client.py",
            commit_sha="sha123456",
        )

        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.category == ChunkCategory.CONTRACT
        assert chunk.id == "agent-cortex:src/cortex/client.py:class_serviceclient"
        assert chunk.breadcrumb == "agent-cortex > src/cortex/client.py > class ServiceClient"
        assert "class ServiceClient(BaseClient, ABC):" in chunk.content
        assert "High-performance API client for upstream cluster." in chunk.content
        assert "endpoint: str" in chunk.content
        assert "timeout: float = 10.0" in chunk.content
        assert "async def fetch_user(self, user_id: str) -> dict[str, str]:" in chunk.content
        assert "def health_check(self) -> bool:" in chunk.content
        assert "def __init__(self, endpoint: str) -> None:" in chunk.content
        assert "_private_helper" not in chunk.content
        assert "python" in chunk.tags
        assert "class" in chunk.tags
        assert "ServiceClient" in chunk.tags
        assert "dataclass" in chunk.tags
        assert "BaseClient" in chunk.tags

    def test_parse_standalone_functions(self) -> None:
        content = """# Utility functions for math

@cached
def calculate_metrics(values: list[float], scale: float = 1.0) -> float:
    \"\"\"Compute aggregate weighted metrics.\"\"\"
    return sum(values) * scale


async def stream_events(topic: str) -> None:
    \"\"\"Stream real-time events from broker.\"\"\"
    pass


def _unexported_calc():
    pass
"""
        parser = PythonContractParser()
        chunks = parser.parse(
            content=content,
            repo="sentinel",
            file_path="sentinel/utils.py",
            commit_sha="sha789",
        )

        assert len(chunks) == 2

        # 1. calculate_metrics
        c1 = chunks[0]
        assert c1.id == "sentinel:sentinel/utils.py:func_calculate_metrics"
        assert c1.breadcrumb == "sentinel > sentinel/utils.py > def calculate_metrics"
        expected_sig = "def calculate_metrics(values: list[float], scale: float = 1.0) -> float:"
        assert expected_sig in c1.content
        assert "Compute aggregate weighted metrics." in c1.content
        assert "cached" in c1.tags

        # 2. stream_events
        c2 = chunks[1]
        assert c2.id == "sentinel:sentinel/utils.py:func_stream_events"
        assert c2.breadcrumb == "sentinel > sentinel/utils.py > async def stream_events"
        assert "async def stream_events(topic: str) -> None:" in c2.content
        assert "async" in c2.tags

    def test_empty_and_broken_syntax(self) -> None:
        parser = PythonContractParser()
        assert parser.parse("", "repo", "file.py", "sha") == []

        # Partial syntax should not crash
        broken = "def incomplete_func(a: int"
        chunks = parser.parse(broken, "repo", "broken.py", "sha")
        assert isinstance(chunks, list)


class TestTypeScriptContractParser:
    def test_parse_interfaces_and_types(self) -> None:
        content = """/**
 * User account contract for auth services.
 */
export interface UserAccount<T = unknown> {
    readonly id: string;
    email: string;
    metadata: T;
    getPermissions(): string[];
}

/**
 * Access token state.
 */
export type TokenState = 'valid' | 'expired' | 'revoked';

export enum UserRole {
    Admin = 'admin',
    Member = 'member',
    Guest = 'guest',
}
"""
        parser = TypeScriptContractParser()
        chunks = parser.parse(
            content=content,
            repo="ia-maestri",
            file_path="src/contracts/user.ts",
            commit_sha="sha999",
        )

        assert len(chunks) == 3

        # Interface
        c_iface = chunks[0]
        assert c_iface.id == "ia-maestri:src/contracts/user.ts:interface_useraccount"
        assert c_iface.breadcrumb == "ia-maestri > src/contracts/user.ts > interface UserAccount"
        assert "export interface UserAccount<T = unknown> {" in c_iface.content
        assert "User account contract for auth services." in c_iface.content
        assert "typescript" in c_iface.tags
        assert "interface" in c_iface.tags

        # Type alias
        c_type = chunks[1]
        assert c_type.id == "ia-maestri:src/contracts/user.ts:type_tokenstate"
        assert c_type.breadcrumb == "ia-maestri > src/contracts/user.ts > type TokenState"
        assert "export type TokenState = 'valid' | 'expired' | 'revoked';" in c_type.content
        assert "type" in c_type.tags

        # Enum
        c_enum = chunks[2]
        assert c_enum.id == "ia-maestri:src/contracts/user.ts:enum_userrole"
        assert c_enum.breadcrumb == "ia-maestri > src/contracts/user.ts > enum UserRole"
        assert "Admin = 'admin'" in c_enum.content

    def test_parse_classes_and_arrow_functions(self) -> None:
        content = """import { BaseService } from './base';

export class SessionManager extends BaseService {
    public timeoutMs: number = 30000;
    private secretKey: string = 'secret';

    public async createSession(userId: string): Promise<string> {
        return 'session_123';
    }

    private refreshInternals(): void {}
}

export const verifySession = async (token: string): Promise<boolean> => {
    return true;
};
"""
        parser = TypeScriptContractParser()
        chunks = parser.parse(
            content=content,
            repo="ia-maestri",
            file_path="src/session.ts",
            commit_sha="sha888",
        )

        assert len(chunks) == 2

        # Class
        cls_chunk = chunks[0]
        assert cls_chunk.id == "ia-maestri:src/session.ts:class_sessionmanager"
        assert cls_chunk.breadcrumb == "ia-maestri > src/session.ts > class SessionManager"
        assert "class SessionManager extends BaseService {" in cls_chunk.content
        assert "public timeoutMs: number = 30000;" in cls_chunk.content
        assert "public async createSession(userId: string): Promise<string>;" in cls_chunk.content
        assert "secretKey" not in cls_chunk.content
        assert "refreshInternals" not in cls_chunk.content

        # Arrow function
        fn_chunk = chunks[1]
        assert fn_chunk.id == "ia-maestri:src/session.ts:func_verifysession"
        assert fn_chunk.breadcrumb == "ia-maestri > src/session.ts > const verifySession"
        expected_arrow = (
            "export const verifySession = async (token: string): Promise<boolean> => ...;"
        )
        assert expected_arrow in fn_chunk.content
        assert "async" in fn_chunk.tags

    def test_tsx_parser(self) -> None:
        content = """export interface ButtonProps {
    label: string;
    onClick: () => void;
}

export function PrimaryButton(props: ButtonProps): JSX.Element {
    return <button onClick={props.onClick}>{props.label}</button>;
}
"""
        parser = TypeScriptContractParser()
        chunks = parser.parse(
            content=content,
            repo="ui-app",
            file_path="src/components/Button.tsx",
            commit_sha="sha777",
        )

        assert len(chunks) == 2
        assert chunks[0].id == "ui-app:src/components/Button.tsx:interface_buttonprops"
        assert chunks[1].id == "ui-app:src/components/Button.tsx:func_primarybutton"
        assert "function PrimaryButton(props: ButtonProps): JSX.Element;" in chunks[1].content


class TestGoContractParser:
    def test_parse_go_types_and_methods(self) -> None:
        content = """package cluster

import "context"

// ClusterStore handles distributed state synchronization.
type ClusterStore interface {
    GetNode(ctx context.Context, id string) (*Node, error)
    RegisterNode(ctx context.Context, node *Node) error
}

// NodeConfig holds node network parameters.
type NodeConfig struct {
    Host string
    Port int
}

// NewClusterStore creates default cluster store.
func NewClusterStore(cfg *NodeConfig) (ClusterStore, error) {
    return nil, nil
}

// SyncState synchronizes internal state with cluster.
func (s *ClusterStore) SyncState(ctx context.Context) error {
    return nil
}

func unexportedInternalFunc() {
}
"""
        parser = GoContractParser()
        chunks = parser.parse(
            content=content,
            repo="node-daemon",
            file_path="pkg/cluster/store.go",
            commit_sha="sha555",
        )

        assert len(chunks) == 4

        # Interface
        c_iface = chunks[0]
        assert c_iface.id == "node-daemon:pkg/cluster/store.go:interface_clusterstore"
        assert c_iface.breadcrumb == "node-daemon > pkg/cluster/store.go > type ClusterStore"
        assert "ClusterStore handles distributed state synchronization." in c_iface.content
        assert "type ClusterStore interface {" in c_iface.content
        assert "go" in c_iface.tags
        assert "interface" in c_iface.tags

        # Struct
        c_struct = chunks[1]
        assert c_struct.id == "node-daemon:pkg/cluster/store.go:struct_nodeconfig"
        assert "type NodeConfig struct {" in c_struct.content
        assert "struct" in c_struct.tags

        # Function
        c_fn = chunks[2]
        assert c_fn.id == "node-daemon:pkg/cluster/store.go:func_newclusterstore"
        assert c_fn.breadcrumb == "node-daemon > pkg/cluster/store.go > func NewClusterStore"
        assert "func NewClusterStore(cfg *NodeConfig) (ClusterStore, error)" in c_fn.content

        # Method
        c_meth = chunks[3]
        assert c_meth.id == "node-daemon:pkg/cluster/store.go:method_clusterstore_syncstate"
        expected_bc = "node-daemon > pkg/cluster/store.go > func (s *ClusterStore) SyncState"
        assert c_meth.breadcrumb == expected_bc
        assert "func (s *ClusterStore) SyncState(ctx context.Context) error" in c_meth.content
        assert "ClusterStore" in c_meth.tags

    def test_skip_test_files(self) -> None:
        parser = GoContractParser()
        chunks = parser.parse(
            content="package cluster\nfunc TestCluster(t *testing.T) {}",
            repo="node-daemon",
            file_path="pkg/cluster/store_test.go",
            commit_sha="sha555",
        )
        assert chunks == []


class TestRegistryAndDispatch:
    def test_registry_resolves_code_parsers(self) -> None:
        assert isinstance(get_parser_for_file("src/main.py"), PythonContractParser)
        assert isinstance(get_parser_for_file("lib/utils.ts"), TypeScriptContractParser)
        assert isinstance(get_parser_for_file("components/Modal.tsx"), TypeScriptContractParser)
        assert isinstance(get_parser_for_file("pkg/server.go"), GoContractParser)

    def test_registry_filters_test_files(self) -> None:
        assert get_parser_for_file("tests/test_api.py") is None
        assert get_parser_for_file("test_utils.py") is None
        assert get_parser_for_file("api_test.py") is None
        assert get_parser_for_file("conftest.py") is None
        assert get_parser_for_file("client.test.ts") is None
        assert get_parser_for_file("modal.spec.tsx") is None
        assert get_parser_for_file("server_test.go") is None

    def test_parse_document_code_integration(self) -> None:
        code = "class Greeter:\n    def greet(self) -> str:\n        return 'hello'\n"
        chunks = parse_document(
            content=code,
            repo="my-repo",
            file_path="greeter.py",
            commit_sha="sha000",
            lifecycle=ChunkLifecycle.ACTIVE,
            scope=ChunkScope.INTERNAL,
        )
        assert len(chunks) == 1
        assert chunks[0].category == ChunkCategory.CONTRACT
        assert chunks[0].id == "my-repo:greeter.py:class_greeter"
