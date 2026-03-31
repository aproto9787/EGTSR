from __future__ import annotations

from egtsr_runtime.compiler.decision_models import DecisionCapsuleV0



def render_capsule(capsule: DecisionCapsuleV0) -> str:
    """Render capsule to human-readable text."""

    lines = ["--- DECISION CAPSULE ---", "## Open Obligations"]
    lines.extend(capsule.header_obligations or ["[None]"])
    lines.append("")
    lines.append("## Warnings")
    lines.extend(capsule.warnings or ["[None]"])
    lines.append("")
    lines.append("## Obligation Details")

    for block in capsule.obligation_blocks:
        lines.append(
            f"### {block.obligation_id} {block.title} (priority: {block.priority}, state: {block.state})"
        )
        lines.extend(_render_items("+ Positive", block.positive_items))
        lines.extend(_render_items("- Negative", block.negative_items))
        lines.extend(_render_items("? Uncertainty", block.uncertainty_items))
        lines.append(f"→ Next: {block.suggested_next_check or '[Unset]'}")
        lines.append("")

    lines.append("## Next Checks")
    lines.extend(capsule.next_checks or ["[None]"])
    lines.append("---")
    return "\n".join(lines)



def _render_items(label: str, items: list[str]) -> list[str]:
    if not items:
        return [f"{label}: [None]"]
    rendered = [f"{label}: {items[0]}"]
    rendered.extend(f"  {item}" for item in items[1:])
    return rendered
