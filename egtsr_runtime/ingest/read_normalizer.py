from __future__ import annotations

from egtsr_runtime.ingest.excerpt import clip_excerpt
from egtsr_runtime.ingest.normalizer import as_text, get_tool_input, get_tool_response, make_evidence


class ReadNormalizer:
    def normalize(self, envelope) -> list:
        """Create evidence from Read tool result."""
        tool_input = get_tool_input(envelope)
        tool_response = get_tool_response(envelope)
        path = as_text(tool_input.get("file_path")) or None
        content = as_text(tool_response.get("content")).strip() or as_text(tool_response).strip()
        return [
            make_evidence(
                envelope,
                kind="read_span",
                source_tool="Read",
                path=path,
                scope_kind="file",
                scope_ref=path,
                polarity="positive",
                excerpt=clip_excerpt(content),
                metadata={"tool_use_id": envelope.tool_use_id},
            )
        ]

    def changed_files(self, envelope) -> list[str]:
        return []
