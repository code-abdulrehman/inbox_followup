import uuid
import json
import threading
import time
from datetime import datetime, timezone
from typing import Optional, Generator

_run_logs = {}
_lock = threading.Lock()
_run_status = {}

def create_run() -> str:
    run_id = str(uuid.uuid4())
    with _lock:
        _run_logs[run_id] = []
        _run_status[run_id] = "running"
    return run_id

def add_log(run_id: str, type: str, step: str, message: str, progress: int = 0):
    with _lock:
        if run_id in _run_logs:
            _run_logs[run_id].append({
                "type": type,
                "step": step,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "progress": progress,
            })

def set_run_status(run_id: str, status: str):
    with _lock:
        _run_status[run_id] = status

def get_run_status(run_id: str) -> Optional[str]:
    with _lock:
        return _run_status.get(run_id)

def get_events_since(run_id: str, after_index: int = 0) -> list:
    with _lock:
        logs = _run_logs.get(run_id, [])
        return logs[after_index:]

def cleanup_run(run_id: str):
    with _lock:
        _run_logs.pop(run_id, None)
        _run_status.pop(run_id, None)

def event_stream(run_id: str) -> Generator[str, None, None]:
    last_index = 0
    while True:
        status = get_run_status(run_id)
        if status is None:
            yield f"data: {json.dumps({'type': 'done', 'message': 'Run completed'})}\n\n"
            break

        events = get_events_since(run_id, last_index)
        for event in events:
            yield f"data: {json.dumps(event)}\n\n"
        last_index += len(events)

        if status in ("success", "failed", "partial_success", "skipped"):
            yield f"data: {json.dumps({'type': 'final', 'status': status})}\n\n"
            break

        time.sleep(0.5)
