"""
otel_tracing.py â€” Distributed Tracing (OpenTelemetry-compatible, stdlib only)
ankavm v2.5.8 Observability

Features:
  - In-memory ring buffer of last 1000 spans
  - start_span / end_span / record_request helpers
  - get_traces / get_trace(trace_id) / export_otlp()
  - configure(otlp_endpoint, enabled) â€” persisted to /var/lib/ankavm/otel_config.json
  - No auto-push: export is on-demand only
"""

from __future__ import annotations
import logging
import json
import time
import uuid
import threading
from pathlib import Path
from collections import deque
from typing import Optional

log = logging.getLogger("otel_tracing")

_CONFIG_FILE = Path("/var/lib/ankavm/otel_config.json")
_lock        = threading.Lock()

# Ring buffer â€” deque with maxlen acts as ring buffer
_BUFFER_SIZE = 1000
_spans: deque = deque(maxlen=_BUFFER_SIZE)

# â”€â”€ Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_DEFAULT_CONFIG = {"otlp_endpoint": "", "enabled": True}


def _load_config() -> dict:
    try:
        if _CONFIG_FILE.exists():
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            cfg = dict(_DEFAULT_CONFIG)
            cfg.update(data)
            return cfg
    except Exception as e:
        log.warning("otel config load fail: %s", e)
    return dict(_DEFAULT_CONFIG)


def _save_config(cfg: dict) -> None:
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CONFIG_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        tmp.replace(_CONFIG_FILE)
    except Exception as e:
        log.warning("otel config save fail: %s", e)


_config: dict = _load_config()


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def configure(otlp_endpoint: str = "", enabled: bool = True) -> dict:
    """Persist OTLP endpoint + enabled flag.  No auto-push side-effect."""
    global _config
    with _lock:
        _config = {"otlp_endpoint": otlp_endpoint.strip(), "enabled": bool(enabled)}
        _save_config(_config)
    return dict(_config)


def get_config() -> dict:
    """Return current config (no secrets to redact here)."""
    with _lock:
        return dict(_config)


def start_span(name: str, parent_id: Optional[str] = None, trace_id: Optional[str] = None) -> dict:
    """Create and store a new span.  Returns the span dict."""
    span_id  = uuid.uuid4().hex
    tid      = trace_id or uuid.uuid4().hex
    span = {
        "span_id":   span_id,
        "trace_id":  tid,
        "parent_id": parent_id,
        "name":      str(name),
        "start_ns":  time.time_ns(),
        "end_ns":    None,
        "duration_ms": None,
        "status":    "UNSET",
        "attributes": {},
        "ts":        int(time.time()),
    }
    with _lock:
        _spans.append(span)
    return span


def end_span(span_id: str, status: str = "OK", attributes: Optional[dict] = None) -> Optional[dict]:
    """Close a span by span_id.  Returns updated span or None if not found."""
    with _lock:
        for sp in reversed(_spans):
            if sp["span_id"] == span_id:
                sp["end_ns"]     = time.time_ns()
                sp["duration_ms"] = round((sp["end_ns"] - sp["start_ns"]) / 1_000_000, 3)
                sp["status"]     = str(status)
                if attributes:
                    sp["attributes"].update(attributes)
                return dict(sp)
    return None


def record_request(method: str, path: str, duration_ms: float, status_code: int) -> dict:
    """Convenience: record a single HTTP request as a completed span."""
    trace_id = uuid.uuid4().hex
    span_id  = uuid.uuid4().hex
    now_ns   = time.time_ns()
    span = {
        "span_id":    span_id,
        "trace_id":   trace_id,
        "parent_id":  None,
        "name":       f"{method} {path}",
        "start_ns":   now_ns - int(duration_ms * 1_000_000),
        "end_ns":     now_ns,
        "duration_ms": round(float(duration_ms), 3),
        "status":     "OK" if status_code < 500 else "ERROR",
        "attributes": {
            "http.method":      method,
            "http.target":      path,
            "http.status_code": status_code,
        },
        "ts": int(time.time()),
    }
    with _lock:
        _spans.append(span)
    return span


def get_traces(limit: int = 100) -> list:
    """Return last `limit` spans (newest first)."""
    with _lock:
        items = list(_spans)
    items.sort(key=lambda s: s["ts"], reverse=True)
    return items[:max(1, limit)]


def get_trace(trace_id: str) -> dict:
    """Return all spans for a given trace_id grouped together."""
    with _lock:
        spans = [dict(s) for s in _spans if s["trace_id"] == trace_id]
    spans.sort(key=lambda s: s["start_ns"])
    return {
        "trace_id": trace_id,
        "span_count": len(spans),
        "spans": spans,
    }


def export_otlp() -> dict:
    """
    Export all buffered spans in OTLP JSON format.
    (Caller can POST this to an OTLP collector manually.)
    """
    with _lock:
        all_spans = list(_spans)

    # Group spans by trace_id
    traces: dict = {}
    for sp in all_spans:
        tid = sp["trace_id"]
        if tid not in traces:
            traces[tid] = []
        traces[tid].append(sp)

    resource_spans = []
    for tid, spans in traces.items():
        scope_spans = []
        for sp in spans:
            otlp_span = {
                "traceId":         sp["trace_id"],
                "spanId":          sp["span_id"],
                "parentSpanId":    sp["parent_id"] or "",
                "name":            sp["name"],
                "kind":            2,  # SPAN_KIND_SERVER
                "startTimeUnixNano": str(sp["start_ns"]),
                "endTimeUnixNano":   str(sp["end_ns"]) if sp["end_ns"] else str(sp["start_ns"]),
                "status": {"code": 2 if sp["status"] == "ERROR" else 1},
                "attributes": [
                    {"key": k, "value": {"stringValue": str(v)}}
                    for k, v in sp.get("attributes", {}).items()
                ],
            }
            scope_spans.append(otlp_span)
        resource_spans.append({
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": "ankavm"}},
                ]
            },
            "scopeSpans": [{"scope": {"name": "ankavm.tracing"}, "spans": scope_spans}],
        })

    return {
        "resourceSpans": resource_spans,
        "exportedAt": int(time.time()),
        "spanCount":  len(all_spans),
    }






