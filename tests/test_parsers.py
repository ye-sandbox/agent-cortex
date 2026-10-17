"""Unit tests for cortex specialized parsers (Markdown, OpenAPI, Docker Compose)."""

from cortex.models.chunk import ChunkCategory, ChunkLifecycle, ChunkScope
from cortex.parsers import (
    DockerComposeParser,
    MarkdownParser,
    OpenAPIParser,
    format_breadcrumb,
    get_parser_for_file,
    parse_document,
    slugify,
)


def test_slugify_and_format_breadcrumb() -> None:
    assert slugify("GET /deals/{id}") == "get_deals_id"
    assert slugify("### Heading 1.2 !!!") == "heading_1_2"
    assert slugify("   ") == "chunk"
    assert (
        format_breadcrumb("sentinel", "specs/openapi.json", "GET /deals")
        == "sentinel > specs/openapi.json > GET /deals"
    )
    assert format_breadcrumb("clipflow", "/compose.yaml") == "clipflow > compose.yaml"


class TestMarkdownParser:
    def test_markdown_hierarchical_headers(self) -> None:
        content = """# Architecture Overview
This is the root overview.

## Storage Engine
We use LanceDB for embedded storage.

### Indexing
IVF-PQ indexing details.

## Retrieval Engine
Hybrid RRF search pipeline.
"""
        parser = MarkdownParser()
        chunks = parser.parse(
            content=content,
            repo="agent-cortex",
            file_path="docs/architecture.md",
            commit_sha="abcdef123456",
        )

        assert len(chunks) == 4
        assert all(c.category == ChunkCategory.DOC for c in chunks)
        assert all(c.repo == "agent-cortex" for c in chunks)
        assert all(c.file_path == "docs/architecture.md" for c in chunks)

        # 1. Architecture Overview
        assert chunks[0].breadcrumb == "agent-cortex > docs/architecture.md > Architecture Overview"
        assert chunks[0].id == "agent-cortex:docs/architecture.md:architecture_overview"
        assert "This is the root overview." in chunks[0].content

        # 2. Storage Engine (child of Architecture Overview)
        assert (
            chunks[1].breadcrumb
            == "agent-cortex > docs/architecture.md > Architecture Overview > Storage Engine"
        )
        assert chunks[1].id == "agent-cortex:docs/architecture.md:storage_engine"
        assert "LanceDB" in chunks[1].content

        # 3. Indexing (child of Storage Engine)
        expected_bc = (
            "agent-cortex > docs/architecture.md > Architecture Overview > "
            "Storage Engine > Indexing"
        )
        assert chunks[2].breadcrumb == expected_bc
        assert chunks[2].id == "agent-cortex:docs/architecture.md:indexing"

        # 4. Retrieval Engine (sibling of Storage Engine, under Architecture Overview)
        assert (
            chunks[3].breadcrumb
            == "agent-cortex > docs/architecture.md > Architecture Overview > Retrieval Engine"
        )
        assert chunks[3].id == "agent-cortex:docs/architecture.md:retrieval_engine"

    def test_markdown_preamble_and_code_fence(self) -> None:
        content = """Preamble introduction before any headers.

# Main Title
Here is some code:

```python
# This is a comment inside code fence, not a markdown header!
def hello():
    return "world"
```

After code block.
"""
        parser = MarkdownParser()
        chunks = parser.parse(
            content=content,
            repo="agent-cortex",
            file_path="README.md",
            commit_sha="sha123",
        )

        assert len(chunks) == 2

        # Preamble chunk
        assert chunks[0].breadcrumb == "agent-cortex > README.md > Intro"
        assert chunks[0].id == "agent-cortex:README.md:intro"
        assert "Preamble introduction" in chunks[0].content

        # Main Title chunk
        assert chunks[1].breadcrumb == "agent-cortex > README.md > Main Title"
        assert chunks[1].id == "agent-cortex:README.md:main_title"
        assert "def hello():" in chunks[1].content
        assert "python" in chunks[1].tags

    def test_markdown_no_headers(self) -> None:
        content = "Just plain text without headers.\nAnother line of text."
        parser = MarkdownParser()
        chunks = parser.parse(
            content=content,
            repo="agent-cortex",
            file_path="notes.txt",
            commit_sha="sha456",
        )

        assert len(chunks) == 1
        assert chunks[0].breadcrumb == "agent-cortex > notes.txt > Intro"
        assert "Just plain text" in chunks[0].content

    def test_markdown_duplicate_header_disambiguation(self) -> None:
        content = """## Overview
First overview.

## Overview
Second overview.
"""
        parser = MarkdownParser()
        chunks = parser.parse(
            content=content,
            repo="agent-cortex",
            file_path="duplicate.md",
            commit_sha="sha999",
        )

        assert len(chunks) == 2
        assert chunks[0].id == "agent-cortex:duplicate.md:overview"
        assert chunks[1].id == "agent-cortex:duplicate.md:overview_1"


class TestOpenAPIParser:
    def test_openapi_json_operations(self) -> None:
        spec = """{
            "openapi": "3.0.0",
            "info": {"title": "Sentinel Deals API", "version": "1.0.0"},
            "paths": {
                "/deals": {
                    "get": {
                        "operationId": "get_deals",
                        "summary": "List all active deals",
                        "tags": ["deals", "sales"],
                        "parameters": [
                            {
                                "name": "limit",
                                "in": "query",
                                "required": false,
                                "schema": {"type": "integer"},
                            }
                        ],
                        "responses": {
                            "200": {"description": "Successful deals list"}
                        }
                    },
                    "post": {
                        "operationId": "create_deal",
                        "summary": "Create new deal",
                        "requestBody": {
                            "description": "Deal payload",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/NewDeal"}
                                }
                            }
                        },
                        "responses": {
                            "201": {"description": "Deal created"}
                        }
                    }
                }
            }
        }"""
        parser = OpenAPIParser()
        chunks = parser.parse(
            content=spec,
            repo="sentinel",
            file_path="specs/openapi.json",
            commit_sha="sha111",
        )

        assert len(chunks) == 2
        assert all(c.category == ChunkCategory.CONTRACT for c in chunks)

        # GET /deals
        get_chunk = next(c for c in chunks if "GET /deals" in c.breadcrumb)
        assert get_chunk.id == "sentinel:specs/openapi.json:get_deals"
        assert get_chunk.breadcrumb == "sentinel > specs/openapi.json > GET /deals"
        assert "List all active deals" in get_chunk.content
        assert "`limit` in `query` [optional]" in get_chunk.content
        assert "GET" in get_chunk.tags
        assert "deals" in get_chunk.tags

        # POST /deals
        post_chunk = next(c for c in chunks if "POST /deals" in c.breadcrumb)
        assert post_chunk.id == "sentinel:specs/openapi.json:create_deal"
        assert "Deal created" in post_chunk.content
        assert "Schema Ref: `#/components/schemas/NewDeal`" in post_chunk.content

    def test_openapi_yaml_without_operation_id(self) -> None:
        yaml_spec = """
openapi: 3.1.0
paths:
  /v1/users/{userId}:
    parameters:
      - name: userId
        in: path
        required: true
        schema:
          type: string
    get:
      summary: Get user profile
      responses:
        "200":
          description: User found
"""
        parser = OpenAPIParser()
        chunks = parser.parse(
            content=yaml_spec,
            repo="clipflow",
            file_path="specs/api.yaml",
            commit_sha="sha222",
        )

        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.category == ChunkCategory.CONTRACT
        assert chunk.id == "clipflow:specs/api.yaml:get_v1_users_userid"
        assert chunk.breadcrumb == "clipflow > specs/api.yaml > GET /v1/users/{userId}"
        assert "`userId` in `path` [required]" in chunk.content
        assert "Get user profile" in chunk.content

    def test_openapi_invalid_content(self) -> None:
        parser = OpenAPIParser()
        chunks = parser.parse(
            content="NOT_A_VALID_SPEC: [unbalanced",
            repo="sentinel",
            file_path="specs/openapi.json",
            commit_sha="sha000",
        )
        assert chunks == []


class TestDockerComposeParser:
    def test_compose_services_and_sanitization(self) -> None:
        compose_content = """
services:
  web:
    image: python:3.12-slim
    ports:
      - "8000:8000"
    environment:
      - PORT=8000
      - DATABASE_URL=postgresql://user@postgres:5432/db
      - DB_PASSWORD=my_super_secret_password
      - API_SECRET_KEY=secret_key_123
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./src:/app/src

  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: cortex
      POSTGRES_PASSWORD: raw_db_password
      POSTGRES_DB: cortex_db
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cortex"]
      interval: 10s
      timeout: 5s
      retries: 5
"""
        parser = DockerComposeParser()
        chunks = parser.parse(
            content=compose_content,
            repo="agent-cortex",
            file_path="compose.yaml",
            commit_sha="sha333",
        )

        assert len(chunks) == 2
        assert all(c.category == ChunkCategory.INFRA for c in chunks)

        # Web service
        web_chunk = next(c for c in chunks if "service_web" in c.id)
        assert web_chunk.breadcrumb == "agent-cortex > compose.yaml > services > web"
        assert web_chunk.id == "agent-cortex:compose.yaml:service_web"
        assert "- **Image:** `python:3.12-slim`" in web_chunk.content
        assert "- PORT=8000" in web_chunk.content
        assert "- DB_PASSWORD=[REDACTED]" in web_chunk.content
        assert "- API_SECRET_KEY=[REDACTED]" in web_chunk.content
        assert "my_super_secret_password" not in web_chunk.content
        assert "secret_key_123" not in web_chunk.content
        assert "8000" in web_chunk.tags

        # Postgres service
        db_chunk = next(c for c in chunks if "service_postgres" in c.id)
        assert db_chunk.breadcrumb == "agent-cortex > compose.yaml > services > postgres"
        assert db_chunk.id == "agent-cortex:compose.yaml:service_postgres"
        assert "- POSTGRES_USER=cortex" in db_chunk.content
        assert "- POSTGRES_PASSWORD=[REDACTED]" in db_chunk.content
        assert "raw_db_password" not in db_chunk.content
        assert "postgres" in db_chunk.tags
        assert "5432" in db_chunk.tags
        assert "Interval: `10s`" in db_chunk.content


class TestRegistryAndDispatcher:
    def test_get_parser_for_file(self) -> None:
        assert isinstance(get_parser_for_file("README.md"), MarkdownParser)
        assert isinstance(get_parser_for_file("docs/adr/001.markdown"), MarkdownParser)
        assert isinstance(get_parser_for_file("compose.yaml"), DockerComposeParser)
        assert isinstance(get_parser_for_file("docker-compose.yml"), DockerComposeParser)
        assert isinstance(get_parser_for_file("specs/openapi.json"), OpenAPIParser)
        assert isinstance(get_parser_for_file("specs/openapi.yaml"), OpenAPIParser)
        assert isinstance(get_parser_for_file("specs/swagger.json"), OpenAPIParser)

    def test_content_heuristic_detection(self) -> None:
        yaml_openapi = "openapi: 3.0.0\npaths:\n  /test:\n    get:\n      summary: Test"
        parser = get_parser_for_file("unnamed_spec.yaml", content=yaml_openapi)
        assert isinstance(parser, OpenAPIParser)

        compose_yaml = "version: '3.8'\nservices:\n  redis:\n    image: redis:alpine"
        parser2 = get_parser_for_file("unknown_stack.yml", content=compose_yaml)
        assert isinstance(parser2, DockerComposeParser)

        assert get_parser_for_file("binary.bin") is None

    def test_parse_document_dispatcher(self) -> None:
        doc = "# Test Doc\nContent inside test document."
        chunks = parse_document(
            content=doc,
            repo="agent-cortex",
            file_path="README.md",
            commit_sha="sha999",
            lifecycle=ChunkLifecycle.ACTIVE,
            scope=ChunkScope.INTERNAL,
        )
        assert len(chunks) == 1
        assert chunks[0].category == ChunkCategory.DOC
        assert chunks[0].repo == "agent-cortex"
