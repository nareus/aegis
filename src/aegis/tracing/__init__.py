"""Tracing infrastructure: span emission, storage, and HTML viewer."""

from aegis.tracing.spans import SpanRecord, Tracer, get_tracer

__all__ = ["SpanRecord", "Tracer", "get_tracer"]
