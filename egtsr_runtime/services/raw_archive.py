from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from egtsr_runtime.hooks.envelopes import HookEnvelope

logger = logging.getLogger(__name__)



def archive_raw_event(raw_events_dir: str, envelope: "HookEnvelope") -> str:
    """Save raw payload to .egtsr/raw_events/ as JSON file."""
    filename = f"{envelope.received_at}_{envelope.hook_event_name}.json"
    output_path = Path(raw_events_dir) / filename
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(envelope.raw, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Failed to archive raw hook event to %s: %s", output_path, exc)
    return str(output_path)
