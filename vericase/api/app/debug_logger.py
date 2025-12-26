import json
from datetime import datetime


def log_debug(location, message, data, hypothesis_id):
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
        with open(
            "c:\\Users\\William\\Documents\\Projects\\VeriCaseJet_canonical\\.cursor\\debug.log",
            "a",
        ) as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception:
        pass
