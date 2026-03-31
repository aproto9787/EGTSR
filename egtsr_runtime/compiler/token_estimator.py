from __future__ import annotations

from dataclasses import replace

from egtsr_runtime.compiler.decision_models import DecisionCapsuleV0, ObligationBlock
from egtsr_runtime.compiler.renderer import render_capsule



def estimate_tokens(text: str) -> int:
    """Estimate token count. Simple heuristic: len(text) // 4"""

    return len(text) // 4



def trim_to_budget(capsule: DecisionCapsuleV0, budget: int) -> DecisionCapsuleV0:
    """Trim capsule content to fit budget."""

    trimmed = replace(
        capsule,
        warnings=list(capsule.warnings),
        obligation_blocks=[
            replace(
                block,
                positive_items=list(block.positive_items),
                negative_items=list(block.negative_items),
                uncertainty_items=list(block.uncertainty_items),
            )
            for block in capsule.obligation_blocks
        ],
    )
    trimmed.rendered_text = render_capsule(trimmed)
    trimmed.token_estimate = estimate_tokens(trimmed.rendered_text)
    if trimmed.token_estimate <= budget:
        return trimmed

    while trimmed.token_estimate > budget and _trim_uncertainty_once(trimmed):
        _rerender(trimmed)
    while trimmed.token_estimate > budget and _trim_positive_once(trimmed):
        _rerender(trimmed)
    while trimmed.token_estimate > budget and trimmed.warnings:
        trimmed.warnings.pop()
        _rerender(trimmed)
    return trimmed



def _trim_uncertainty_once(capsule: DecisionCapsuleV0) -> bool:
    for block in reversed(capsule.obligation_blocks):
        if block.uncertainty_items:
            block.uncertainty_items.pop()
            return True
    return False



def _trim_positive_once(capsule: DecisionCapsuleV0) -> bool:
    for block in reversed(capsule.obligation_blocks):
        if block.positive_items:
            block.positive_items.pop()
            return True
    return False



def _rerender(capsule: DecisionCapsuleV0) -> None:
    capsule.rendered_text = render_capsule(capsule)
    capsule.token_estimate = estimate_tokens(capsule.rendered_text)
