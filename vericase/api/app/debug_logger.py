import json
from datetime import datetime
import os
from pathlib import Path

from .config import settings


def log_debug(location, message, data, hypothesis_id):
    if not bool(getattr(settings, "PST_AGENT_LOG_ENABLED", False)):
        return
    try:
        log_entry = {
            "sessionId": "debug-session",
            "runId": "run1",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(datetime.now().timestamp() * 1000),
        }
        log_path = (
            os.getenv("PST_AGENT_LOG_PATH")
            or getattr(settings, "PST_AGENT_LOG_PATH", None)
            or os.getenv("VERICASE_DEBUG_LOG_PATH")
            or str(Path(".cursor") / "debug.log")
        )
        try:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
