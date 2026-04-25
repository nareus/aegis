"""HTML rendering for agent trace trees."""

import html
import json
from collections import defaultdict
from datetime import datetime
from uuid import UUID

_PAGE_CSS = """
body { font-family: -apple-system, system-ui, sans-serif; max-width: 1100px;
       margin: 2em auto; padding: 0 1em; color: #1f2328; }
h1 { font-size: 1.4em; }
.meta { color: #57606a; font-size: 0.9em; margin-bottom: 1.5em; }
.span { border-left: 3px solid #d0d7de; padding: 0.5em 0.8em; margin: 0.4em 0; }
.span.error { border-left-color: #cf222e; background: #fff8f8; }
.span .header { font-weight: 600; }
.span .badges { color: #57606a; font-size: 0.85em; margin-left: 0.5em; }
.children { margin-left: 1.2em; }
details { margin: 0.3em 0; }
summary { cursor: pointer; color: #0969da; font-size: 0.9em; }
pre { background: #f6f8fa; padding: 0.6em; border-radius: 6px;
      overflow-x: auto; font-size: 0.85em; }
.error-msg { color: #cf222e; font-family: monospace; margin-top: 0.4em; }
"""


def render_trace_html(run_id: UUID, spans: list[dict]) -> str:
    """Render a complete HTML page for a run's span tree."""
    if not spans:
        return _empty_page(run_id)

    by_parent: dict[UUID | None, list[dict]] = defaultdict(list)
    for span in spans:
        by_parent[span["parent_span_id"]].append(span)

    total_cost = sum(float(s["cost_usd"] or 0) for s in spans)
    total_latency = max(
        (s["latency_ms"] or 0 for s in spans if s["parent_span_id"] is None),
        default=0,
    )
    span_count = len(spans)
    error_count = sum(1 for s in spans if s["error"])

    body_parts: list[str] = []
    for root in by_parent[None]:
        body_parts.append(_render_span(root, by_parent))

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Trace {run_id}</title>
<style>{_PAGE_CSS}</style></head>
<body>
<h1>Trace <code>{run_id}</code></h1>
<div class="meta">
  {span_count} spans · ${total_cost:.4f} · {total_latency} ms
  {f' · <span style="color:#cf222e">{error_count} error(s)</span>' if error_count else ''}
</div>
{''.join(body_parts)}
</body></html>"""


def _render_span(span: dict, by_parent: dict[UUID | None, list[dict]]) -> str:
    cls = "span error" if span["error"] else "span"
    cost = float(span["cost_usd"] or 0)
    latency = span["latency_ms"] or 0
    tokens = (span["input_tokens"] or 0, span["output_tokens"] or 0)

    children_html = "".join(
        _render_span(child, by_parent) for child in by_parent.get(span["id"], [])
    )

    error_html = (
        f'<div class="error-msg">{html.escape(span["error"])}</div>'
        if span["error"] else ""
    )

    return f"""
<div class="{cls}">
  <div class="header">
    {html.escape(span["agent_name"])}
    <span class="badges">
      {html.escape(span["workflow"])} · {latency} ms · ${cost:.4f}
      · {tokens[0]}+{tokens[1]} tok
    </span>
  </div>
  {error_html}
  <details><summary>input</summary><pre>{_pretty_json(span["input_payload"])}</pre></details>
  {_output_block(span["output_payload"])}
  <div class="children">{children_html}</div>
</div>"""


def _output_block(payload: object) -> str:
    if payload is None:
        return ""
    return f'<details><summary>output</summary><pre>{_pretty_json(payload)}</pre></details>'


def _pretty_json(payload: object) -> str:
    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, indent=2, default=_json_default)
    elif isinstance(payload, str):
        try:
            text = json.dumps(json.loads(payload), indent=2, default=_json_default)
        except (ValueError, TypeError):
            text = payload
    else:
        text = json.dumps(payload, default=_json_default)
    return html.escape(text)


def _json_default(obj: object) -> str:
    if isinstance(obj, (UUID, datetime)):
        return str(obj)
    raise TypeError(f"not JSON-serializable: {type(obj).__name__}")


def _empty_page(run_id: UUID) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Trace {run_id}</title>
<style>{_PAGE_CSS}</style></head>
<body>
<h1>Trace <code>{run_id}</code></h1>
<p class="meta">No spans recorded for this run.</p>
</body></html>"""
