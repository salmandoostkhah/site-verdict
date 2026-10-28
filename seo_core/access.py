"""دسترسی امن به فیلدها؛ چه در قالب دیکشنری و چه در قالب آبجکت Pydantic."""
from __future__ import annotations


def get_val(obj, key, default="—"):
    """دسترسی امن به فیلدها چه در قالب دیکشنری و چه در قالب آبجکت Pydantic"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)