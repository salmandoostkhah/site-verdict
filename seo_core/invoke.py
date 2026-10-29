"""Helpers for locating and invoking analyzer callables safely."""

import asyncio
import inspect
from typing import Any, Dict, Optional


def _get_callable(obj: Any, default_attr: str = "analyze") -> Optional[Any]:
    """استخراج تابع اجرایی در صورت ایمپورت شدن ماژول."""
    if obj is None:
        return None
    if callable(obj) and not hasattr(obj, "__file__"):
        return obj
    if hasattr(obj, default_attr) and callable(getattr(obj, default_attr)):
        return getattr(obj, default_attr)
    if hasattr(obj, f"analyze_{default_attr}") and callable(getattr(obj, f"analyze_{default_attr}")):
        return getattr(obj, f"analyze_{default_attr}")
    return obj if callable(obj) else None


def _filter_supported_kwargs(func: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """فیلتر هوشمند آرگومان‌ها متناسب با امضای دقیق تابع."""
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return {}

    parameters = signature.parameters

    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        return dict(kwargs)

    return {
        key: value
        for key, value in kwargs.items()
        if key in parameters
        and parameters[key].kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }


async def _invoke_analyzer(
    func: Any,
    *args: Any,
    **optional_kwargs: Any,
) -> Any:
    """اجرای ناهمگام و ایزوله تحلیل‌گرها بدون مسدودسازی Event Loop."""
    kwargs = _filter_supported_kwargs(func, optional_kwargs)

    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)

    result = await asyncio.to_thread(func, *args, **kwargs)
    if inspect.isawaitable(result):
        return await result

    return result