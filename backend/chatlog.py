"""JSON chat logs for the RCA Code CLI.

Every CLI session writes one file under ``<project root>/logs/``. The file is
rewritten after every recorded event, so a crash still leaves the conversation
on disk (a log whose ``ended_at`` is ``null`` did not exit cleanly).

Two views of the session are stored:

* ``messages`` - the raw message list exactly as it is handed to the model,
  including function calls and tool results, ready for replay by newer
  features.
* ``entries`` - a flat, chronological list of typed events: user turns,
  assistant replies (with their ``thoughts`` and token stats), tool calls
  (with arguments, results, and the model's reasoning for calling them),
  ``/thinking`` lookups, model switches, and errors.
"""

import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")

# Whitelist of model fields that are safe to persist. The API key is
# deliberately absent.
MODEL_FIELDS = ("id", "label", "provider", "model", "temperature", "base_url")


def _now():
    return datetime.now().isoformat(timespec="seconds")


def describe_model(settings):
    """Return a JSON-safe description of model settings without secrets."""
    return {field: getattr(settings, field, None) for field in MODEL_FIELDS}


class ChatLog:
    """One session's chat log, persisted as JSON after every event."""

    def __init__(self, model, messages=None, log_dir=LOG_DIR):
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.session_id = f"chat-{stamp}"
        self.path = os.path.join(self.log_dir, f"{self.session_id}.json")
        # Live reference to the CLI's conversation history, saved as-is so the
        # raw view always matches what the model was sent.
        self._messages = messages if messages is not None else []
        self.data = {
            "session_id": self.session_id,
            "started_at": _now(),
            "ended_at": None,
            "model": model,
            "entries": [],
            "messages": self._messages,
        }
        self.save()

    def record(self, entry):
        """Append a typed entry (stamped with a timestamp) and persist."""
        entry = dict(entry)
        entry.setdefault("at", _now())
        self.data["entries"].append(entry)
        self.save()
        return entry

    def set_model(self, model):
        """Record a model switch and make it the log's active model."""
        self.data["model"] = model
        self.record({"type": "model_switch", "model": model})

    def save(self):
        """Write the whole log to disk (small files, rewritten each call)."""
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    def close(self):
        """Stamp the session as cleanly finished and write the final log."""
        self.data["ended_at"] = _now()
        self.save()
