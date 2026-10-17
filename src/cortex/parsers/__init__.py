"""Specialized semantic chunkers and parsers for agent-cortex."""

from cortex.parsers.base import BaseParser, format_breadcrumb, slugify
from cortex.parsers.compose import DockerComposeParser
from cortex.parsers.markdown import MarkdownParser
from cortex.parsers.openapi import OpenAPIParser
from cortex.parsers.registry import get_parser_for_file, parse_document

__all__ = [
    "BaseParser",
    "DockerComposeParser",
    "MarkdownParser",
    "OpenAPIParser",
    "format_breadcrumb",
    "get_parser_for_file",
    "parse_document",
    "slugify",
]
