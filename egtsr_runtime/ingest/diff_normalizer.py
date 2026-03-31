from __future__ import annotations

import re

from egtsr_runtime.ingest.excerpt import clip_excerpt
from egtsr_runtime.ingest.normalizer import as_text, get_tool_input, get_tool_response, make_evidence


class DiffNormalizer:
    def normalize(self, envelope) -> list:
        """Create evidence from Write/Edit/Diff tool result."""
        source_tool = envelope.tool_name or "Diff"
        tool_response = get_tool_response(envelope)
        changed_files = self.changed_files(envelope)
        status = as_text(tool_response.get("status")).strip()
        path = changed_files[0] if len(changed_files) == 1 else None
        excerpt = self._build_excerpt(source_tool, changed_files, status)

        return [
            make_evidence(
                envelope,
                kind="diff_meta",
                source_tool=source_tool,
                path=path,
                scope_kind="file" if path else "change",
                scope_ref=path or source_tool,
                polarity="positive",
                excerpt=clip_excerpt(excerpt),
                metadata={
                    "tool_use_id": envelope.tool_use_id,
                    "changed_files": changed_files,
                    "status": status,
                },
            )
        ]

    def changed_files(self, envelope) -> list[str]:
        """Extract changed file paths from tool payloads."""
        tool_name = envelope.tool_name or ""
        tool_input = get_tool_input(envelope)
        tool_response = get_tool_response(envelope)
        if tool_name in {"Write", "Edit"}:
            path = as_text(tool_input.get("file_path")).strip()
            return [path] if path else []
        if tool_name == "Diff":
            files = tool_response.get("changed_files") or tool_response.get("files")
            if isinstance(files, list):
                return [as_text(item).strip() for item in files if as_text(item).strip()]
            diff_text = "\n".join(
                part
                for part in (
                    as_text(tool_response.get("diff")).strip(),
                    as_text(tool_response.get("content")).strip(),
                    as_text(tool_response.get("stdout")).strip(),
                )
                if part
            )
            if not diff_text:
                return []
            matches = re.findall(r"^\+\+\+\s+b/(.+)$", diff_text, flags=re.MULTILINE)
            if not matches:
                matches = re.findall(r"^diff --git a/.+ b/(.+)$", diff_text, flags=re.MULTILINE)
            deduped: list[str] = []
            seen: set[str] = set()
            for match in matches:
                cleaned = match.strip()
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    deduped.append(cleaned)
            return deduped
        return []

    @staticmethod
    def _build_excerpt(source_tool: str, changed_files: list[str], status: str) -> str:
        verb = {
            "Write": "wrote",
            "Edit": "updated",
            "Diff": "reported",
        }.get(source_tool, "changed")
        summary = f"{source_tool} {verb}"
        if changed_files:
            summary += f" {len(changed_files)} file(s): {', '.join(changed_files)}"
        if status:
            summary += f"; status={status}"
        return summary
