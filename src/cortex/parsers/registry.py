"""Parser registry and dispatcher for agent-cortex."""

from __future__ import annotations

import os
import re

from cortex.models.chunk import ChunkLifecycle, ChunkScope, DocumentChunk
from cortex.parsers.base import BaseParser
from cortex.parsers.compose import DockerComposeParser
from cortex.parsers.markdown import MarkdownParser
from cortex.parsers.openapi import OpenAPIParser

_COMPOSE_FILENAME_REGEX = re.compile(r"^(docker-)?compose.*\.ya?ml$", re.IGNORECASE)
_OPENAPI_FILENAME_REGEX = re.compile(r"^(open-?api|swagger).*\.(ya?ml|json)$", re.IGNORECASE)
_MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkdn"}


def get_parser_for_file(file_path: str, content: str | None = None) -> BaseParser | None:
    """Resolve the appropriate domain parser based on path and optional content hints."""
    basename = os.path.basename(file_path).lower()
    _, ext = os.path.splitext(basename)

    # 1. Docker Compose
    if _COMPOSE_FILENAME_REGEX.match(basename):
        return DockerComposeParser()

    # 2. OpenAPI / Swagger files
    if _OPENAPI_FILENAME_REGEX.match(basename):
        return OpenAPIParser()

    # 3. Markdown files
    if ext in _MARKDOWN_EXTENSIONS:
        return MarkdownParser()

    # 4. Content-based detection for ambiguous JSON/YAML
    if content:
        stripped = content.lstrip()
        if ext in {".yaml", ".yml", ".json"}:
            if (
                '"openapi"' in content
                or "openapi:" in content
                or '"swagger"' in content
                or "swagger:" in content
            ):
                return OpenAPIParser()
            if "services:" in content and ("version:" in content or "volumes:" in content):
                return DockerComposeParser()

        # Markdown header fallback
        if stripped.startswith("#"):
            return MarkdownParser()

    return None


def parse_document(
    content: str,
    repo: str,
    file_path: str,
    commit_sha: str,
    lifecycle: ChunkLifecycle = ChunkLifecycle.ACTIVE,
    scope: ChunkScope = ChunkScope.INTERNAL,
    parser: BaseParser | None = None,
) -> list[DocumentChunk]:
    """Parse a document using the resolved or explicitly supplied parser."""
    target_parser = parser or get_parser_for_file(file_path, content)
    if target_parser is None:
        return []

    return target_parser.parse(
        content=content,
        repo=repo,
        file_path=file_path,
        commit_sha=commit_sha,
        lifecycle=lifecycle,
        scope=scope,
    )
