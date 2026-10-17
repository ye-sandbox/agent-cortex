"""Markdown section chunker with hierarchical breadcrumb tracking."""

from __future__ import annotations

import re

from cortex.models.chunk import ChunkCategory, ChunkLifecycle, ChunkScope, DocumentChunk
from cortex.parsers.base import BaseParser, format_breadcrumb, slugify

HEADER_REGEX = re.compile(r"^(#{1,6})\s+(.+)$")
FENCE_REGEX = re.compile(r"^(`{3,}|~{3,})(.*)$")


class MarkdownParser(BaseParser):
    """Chunks Markdown documents by headers while maintaining structural hierarchy."""

    def parse(
        self,
        content: str,
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle = ChunkLifecycle.ACTIVE,
        scope: ChunkScope = ChunkScope.INTERNAL,
    ) -> list[DocumentChunk]:
        """Split markdown content by headers into DocumentChunk records."""
        lines = content.splitlines()
        chunks: list[DocumentChunk] = []

        # State tracking
        in_code_block = False
        active_fence = ""
        header_stack: list[tuple[int, str]] = []  # (level, title)

        current_lines: list[str] = []
        current_header: str | None = None
        current_breadcrumb_parts: list[str] = []
        current_code_langs: set[str] = set()

        seen_slugs: dict[str, int] = {}

        def flush_current_chunk() -> None:
            nonlocal current_lines, current_header, current_breadcrumb_parts, current_code_langs
            text = "\n".join(current_lines).strip()
            if not text:
                current_lines = []
                current_code_langs = set()
                return

            if current_header:
                base_slug = slugify(current_header)
            elif current_breadcrumb_parts:
                base_slug = slugify(current_breadcrumb_parts[-1])
            else:
                base_slug = "intro" if chunks else "main"

            count = seen_slugs.get(base_slug, 0)
            seen_slugs[base_slug] = count + 1
            chunk_suffix = base_slug if count == 0 else f"{base_slug}_{count}"

            breadcrumb = format_breadcrumb(repo, file_path, *current_breadcrumb_parts)

            tags: list[str] = []
            for part in current_breadcrumb_parts:
                part_slug = slugify(part)
                if part_slug and part_slug not in tags:
                    tags.append(part_slug)
            for lang in sorted(current_code_langs):
                if lang and lang not in tags:
                    tags.append(lang)

            chunk = DocumentChunk(
                id=DocumentChunk.build_id(repo, file_path, chunk_suffix),
                repo=repo,
                file_path=file_path,
                category=ChunkCategory.DOC,
                lifecycle=lifecycle,
                scope=scope,
                breadcrumb=breadcrumb,
                commit_sha=commit_sha,
                tags=tags,
                content=text,
            )
            chunks.append(chunk)

            current_lines = []
            current_code_langs = set()

        for line in lines:
            stripped = line.strip()

            # Check for code fence start/end
            fence_match = FENCE_REGEX.match(stripped)
            if fence_match:
                fence_chars = fence_match.group(1)
                fence_info = fence_match.group(2).strip().lower()

                if not in_code_block:
                    in_code_block = True
                    active_fence = fence_chars[:3]
                    if fence_info:
                        # Grab first token as language (e.g., 'python' from 'python {class=foo}')
                        lang = fence_info.split()[0]
                        current_code_langs.add(lang)
                elif fence_chars.startswith(active_fence):
                    in_code_block = False
                    active_fence = ""

                current_lines.append(line)
                continue

            # If inside code fence, header markers are just code/comments
            if in_code_block:
                current_lines.append(line)
                continue

            # Check for markdown header
            header_match = HEADER_REGEX.match(stripped)
            if header_match:
                level = len(header_match.group(1))
                title = header_match.group(2).strip()

                # Flush content accumulated prior to this header
                flush_current_chunk()

                # Update header hierarchy stack
                while header_stack and header_stack[-1][0] >= level:
                    header_stack.pop()
                header_stack.append((level, title))

                current_header = title
                current_breadcrumb_parts = [h[1] for h in header_stack]
                current_lines.append(line)
            else:
                if not current_breadcrumb_parts and not chunks and not current_lines:
                    # Content before the first header (preamble/intro)
                    current_breadcrumb_parts = ["Intro"]
                current_lines.append(line)

        # Flush any trailing chunk
        flush_current_chunk()

        return chunks
