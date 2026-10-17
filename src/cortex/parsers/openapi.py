"""OpenAPI contract parser chunking by endpoint operation."""

from __future__ import annotations

import json
from typing import cast

import yaml

from cortex.models.chunk import ChunkCategory, ChunkLifecycle, ChunkScope, DocumentChunk
from cortex.parsers.base import BaseParser, format_breadcrumb, slugify

SUPPORTED_METHODS = ("get", "post", "put", "delete", "patch", "options", "head", "trace")


class OpenAPIParser(BaseParser):
    """Chunks OpenAPI and Swagger specifications by individual endpoint operations."""

    def parse(
        self,
        content: str,
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle = ChunkLifecycle.ACTIVE,
        scope: ChunkScope = ChunkScope.INTERNAL,
    ) -> list[DocumentChunk]:
        """Parse OpenAPI specification into operation-level DocumentChunks."""
        raw_data: object
        try:
            raw_data = json.loads(content)
        except Exception:
            try:
                raw_data = yaml.safe_load(content)
            except Exception:
                return []

        if not isinstance(raw_data, dict):
            return []

        spec = cast(dict[str, object], raw_data)
        raw_paths = spec.get("paths")
        if not isinstance(raw_paths, dict):
            return []

        paths = cast(dict[str, object], raw_paths)
        chunks: list[DocumentChunk] = []
        seen_slugs: dict[str, int] = {}

        for path_str, path_obj in paths.items():
            if not isinstance(path_obj, dict):
                continue
            path_item = cast(dict[str, object], path_obj)
            path_params = path_item.get("parameters")
            shared_params: list[dict[str, object]] = []
            if isinstance(path_params, list):
                shared_params = [
                    cast(dict[str, object], p) for p in path_params if isinstance(p, dict)
                ]

            for method_key in SUPPORTED_METHODS:
                op_obj = path_item.get(method_key)
                if not isinstance(op_obj, dict):
                    continue
                op = cast(dict[str, object], op_obj)
                method_upper = method_key.upper()

                # Operation attributes
                summary = str(op.get("summary", "")).strip()
                description = str(op.get("description", "")).strip()
                op_id = str(op.get("operationId", "")).strip()

                op_tags_raw = op.get("tags")
                op_tags: list[str] = []
                if isinstance(op_tags_raw, list):
                    op_tags = [str(t).strip() for t in op_tags_raw if str(t).strip()]

                # Combine path-level and operation-level parameters
                merged_params: list[dict[str, object]] = list(shared_params)
                op_params = op.get("parameters")
                if isinstance(op_params, list):
                    merged_params.extend(
                        [cast(dict[str, object], p) for p in op_params if isinstance(p, dict)]
                    )

                # Build readable content block
                content_lines: list[str] = [f"### {method_upper} {path_str}"]
                if summary:
                    content_lines.append(f"**Summary:** {summary}")
                if description:
                    content_lines.append(f"**Description:** {description}")
                if op_id:
                    content_lines.append(f"**Operation ID:** `{op_id}`")
                if op_tags:
                    content_lines.append(f"**Tags:** {', '.join(op_tags)}")

                if merged_params:
                    content_lines.append("\n**Parameters:**")
                    for param in merged_params:
                        p_name = str(param.get("name", "unknown"))
                        p_in = str(param.get("in", "query"))
                        p_req = "required" if param.get("required") is True else "optional"
                        p_desc = str(param.get("description", "")).strip()

                        schema_info = ""
                        p_schema = param.get("schema")
                        if isinstance(p_schema, dict):
                            p_type = p_schema.get("type", "")
                            if p_type:
                                schema_info = f" (type: {p_type})"

                        desc_str = f" - {p_desc}" if p_desc else ""
                        content_lines.append(
                            f"- `{p_name}` in `{p_in}` [{p_req}]{schema_info}{desc_str}"
                        )

                # Request Body
                req_body = op.get("requestBody")
                if isinstance(req_body, dict):
                    content_lines.append("\n**Request Body:**")
                    rb_desc = str(req_body.get("description", "")).strip()
                    if rb_desc:
                        content_lines.append(f"- Description: {rb_desc}")
                    rb_content = req_body.get("content")
                    if isinstance(rb_content, dict):
                        for media_type, media_obj in rb_content.items():
                            content_lines.append(f"- Media Type: `{media_type}`")
                            if isinstance(media_obj, dict):
                                schema_obj = media_obj.get("schema")
                                if isinstance(schema_obj, dict):
                                    ref = schema_obj.get("$ref")
                                    if ref:
                                        content_lines.append(f"  Schema Ref: `{ref}`")

                # Responses
                responses = op.get("responses")
                if isinstance(responses, dict):
                    content_lines.append("\n**Responses:**")
                    for status_code, resp_obj in responses.items():
                        if isinstance(resp_obj, dict):
                            r_desc = str(resp_obj.get("description", "")).strip()
                            r_content = resp_obj.get("content")
                            r_schema_info = ""
                            if isinstance(r_content, dict):
                                json_content = r_content.get("application/json")
                                if isinstance(json_content, dict):
                                    schema_obj = json_content.get("schema")
                                    if isinstance(schema_obj, dict):
                                        ref = schema_obj.get("$ref")
                                        if ref:
                                            r_schema_info = f" -> `{ref}`"
                            content_lines.append(f"- `{status_code}`: {r_desc}{r_schema_info}")

                # Build deterministic chunk ID
                if op_id:
                    base_slug = slugify(op_id)
                else:
                    path_slug = slugify(path_str.replace("/", "_"))
                    base_slug = f"{method_key}_{path_slug}"

                count = seen_slugs.get(base_slug, 0)
                seen_slugs[base_slug] = count + 1
                chunk_suffix = base_slug if count == 0 else f"{base_slug}_{count}"

                breadcrumb = format_breadcrumb(repo, file_path, f"{method_upper} {path_str}")

                # Extract tags
                tags: list[str] = [method_upper, method_key]
                for seg in path_str.split("/"):
                    clean_seg = seg.strip("{}")
                    if clean_seg and clean_seg not in tags:
                        tags.append(clean_seg)
                for t in op_tags:
                    t_slug = slugify(t)
                    if t_slug and t_slug not in tags:
                        tags.append(t_slug)

                chunk = DocumentChunk(
                    id=DocumentChunk.build_id(repo, file_path, chunk_suffix),
                    repo=repo,
                    file_path=file_path,
                    category=ChunkCategory.CONTRACT,
                    lifecycle=lifecycle,
                    scope=scope,
                    breadcrumb=breadcrumb,
                    commit_sha=commit_sha,
                    tags=tags,
                    content="\n".join(content_lines).strip(),
                )
                chunks.append(chunk)

        return chunks
