"""Docker Compose parser chunking manifests by service definition."""

from __future__ import annotations

import re
from typing import cast

import yaml

from cortex.models.chunk import ChunkCategory, ChunkLifecycle, ChunkScope, DocumentChunk
from cortex.parsers.base import BaseParser, format_breadcrumb, slugify

SENSITIVE_ENV_PATTERN = re.compile(
    r"(secret|token|key|password|passwd|auth|credential|private|cert)",
    re.IGNORECASE,
)


class DockerComposeParser(BaseParser):
    """Chunks Docker Compose files by individual service under 'services'."""

    def _sanitize_env_var(self, env_entry: str | dict[str, object]) -> str:
        """Sanitize an environment variable entry, masking potential secrets."""
        if isinstance(env_entry, dict):
            # Form: {name: "KEY", value: "VAL"} or similar
            name = str(env_entry.get("name", ""))
            val = str(env_entry.get("value", ""))
            if SENSITIVE_ENV_PATTERN.search(name):
                return f"- {name}=[REDACTED]"
            return f"- {name}={val}"

        # String form: "KEY=VALUE" or "KEY"
        text = str(env_entry).strip()
        if "=" in text:
            k, _ = text.split("=", 1)
            clean_k = k.strip()
            if SENSITIVE_ENV_PATTERN.search(clean_k):
                return f"- {clean_k}=[REDACTED]"
            return f"- {text}"

        # Standalone variable without value (e.g. forwarded from host)
        if SENSITIVE_ENV_PATTERN.search(text):
            return f"- {text}=[REDACTED]"
        return f"- {text}"

    def parse(
        self,
        content: str,
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle = ChunkLifecycle.ACTIVE,
        scope: ChunkScope = ChunkScope.INTERNAL,
    ) -> list[DocumentChunk]:
        """Parse Docker Compose content into service-level DocumentChunks."""
        try:
            raw_data = yaml.safe_load(content)
        except Exception:
            return []

        if not isinstance(raw_data, dict):
            return []

        data = cast(dict[str, object], raw_data)
        services_raw = data.get("services")
        if not isinstance(services_raw, dict):
            return []

        services = cast(dict[str, object], services_raw)
        chunks: list[DocumentChunk] = []
        seen_slugs: dict[str, int] = {}

        for svc_name, svc_obj in services.items():
            if not isinstance(svc_obj, dict):
                continue
            svc = cast(dict[str, object], svc_obj)

            content_lines: list[str] = [f"### Service: {svc_name}"]
            tags: list[str] = ["infra", "docker-compose", svc_name]

            # Image or Build
            image = svc.get("image")
            if image:
                image_str = str(image).strip()
                content_lines.append(f"- **Image:** `{image_str}`")
                # Add base image name to tags (e.g., 'postgres:16' -> 'postgres')
                base_img = image_str.split(":")[0].split("/")[-1]
                if base_img and base_img not in tags:
                    tags.append(base_img)

            build = svc.get("build")
            if build:
                if isinstance(build, dict):
                    build_dict = cast(dict[str, object], build)
                    ctx = build_dict.get("context", ".")
                    target = build_dict.get("target")
                    target_str = f" (target: {target})" if target else ""
                    content_lines.append(f"- **Build Context:** `{ctx}`{target_str}")
                else:
                    content_lines.append(f"- **Build:** `{build}`")

            container_name = svc.get("container_name")
            if container_name:
                content_lines.append(f"- **Container Name:** `{container_name}`")

            restart = svc.get("restart")
            if restart:
                content_lines.append(f"- **Restart Policy:** `{restart}`")

            # Ports
            ports = svc.get("ports")
            if isinstance(ports, list) and ports:
                content_lines.append("\n**Ports:**")
                for port_entry in ports:
                    p_str = str(port_entry).strip()
                    content_lines.append(f"- `{p_str}`")
                    # Extract port digits for search tags
                    port_digits = re.findall(r"\b\d{2,5}\b", p_str)
                    for pd in port_digits:
                        if pd not in tags:
                            tags.append(pd)

            # Volumes
            volumes = svc.get("volumes")
            if isinstance(volumes, list) and volumes:
                content_lines.append("\n**Volumes:**")
                for vol_entry in volumes:
                    content_lines.append(f"- `{vol_entry}`")

            # Environment
            env = svc.get("environment")
            if env:
                content_lines.append("\n**Environment:**")
                if isinstance(env, list):
                    for e in env:
                        content_lines.append(self._sanitize_env_var(e))
                elif isinstance(env, dict):
                    for k, v in env.items():
                        clean_k = str(k).strip()
                        if SENSITIVE_ENV_PATTERN.search(clean_k):
                            content_lines.append(f"- {clean_k}=[REDACTED]")
                        else:
                            content_lines.append(f"- {clean_k}={v}")

            # Depends on
            depends_on = svc.get("depends_on")
            if depends_on:
                content_lines.append("\n**Depends On:**")
                if isinstance(depends_on, list):
                    for dep in depends_on:
                        content_lines.append(f"- `{dep}`")
                elif isinstance(depends_on, dict):
                    for dep_svc, dep_cfg in depends_on.items():
                        cond_str = ""
                        if isinstance(dep_cfg, dict):
                            condition = dep_cfg.get("condition")
                            if condition:
                                cond_str = f" (condition: {condition})"
                        content_lines.append(f"- `{dep_svc}`{cond_str}")

            # Healthcheck
            healthcheck = svc.get("healthcheck")
            if isinstance(healthcheck, dict):
                content_lines.append("\n**Healthcheck:**")
                test = healthcheck.get("test")
                if test:
                    content_lines.append(f"- Test: `{test}`")
                interval = healthcheck.get("interval")
                if interval:
                    content_lines.append(f"- Interval: `{interval}`")
                timeout = healthcheck.get("timeout")
                if timeout:
                    content_lines.append(f"- Timeout: `{timeout}`")
                retries = healthcheck.get("retries")
                if retries is not None:
                    content_lines.append(f"- Retries: `{retries}`")

            # Networks
            networks = svc.get("networks")
            if networks:
                content_lines.append("\n**Networks:**")
                if isinstance(networks, (list, dict)):
                    for net in networks:
                        content_lines.append(f"- `{net}`")

            # Deterministic chunk ID
            base_slug = f"service_{slugify(svc_name)}"
            count = seen_slugs.get(base_slug, 0)
            seen_slugs[base_slug] = count + 1
            chunk_suffix = base_slug if count == 0 else f"{base_slug}_{count}"

            breadcrumb = format_breadcrumb(repo, file_path, "services", svc_name)

            chunk = DocumentChunk(
                id=DocumentChunk.build_id(repo, file_path, chunk_suffix),
                repo=repo,
                file_path=file_path,
                category=ChunkCategory.INFRA,
                lifecycle=lifecycle,
                scope=scope,
                breadcrumb=breadcrumb,
                commit_sha=commit_sha,
                tags=tags,
                content="\n".join(content_lines).strip(),
            )
            chunks.append(chunk)

        return chunks
