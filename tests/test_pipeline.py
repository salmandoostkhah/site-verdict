import asyncio
import functools
from types import SimpleNamespace

import pytest

from seo_core.pipeline import (
    AuditContext,
    DuplicateStageError,
    Stage,
    StageRegistry,
    StageResult,
    normalize_result,
    run_stages,
)


def run_async(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


def _ctx():
    return AuditContext(url="https://example.com", report=SimpleNamespace(failed_analyzers=[]))


def _stage(name, result=None, order=100, **kw):
    async def run(ctx):
        return result
    return Stage(name=name, run=run, order=order, **kw)


def test_normalize_variants():
    assert normalize_result(None) == StageResult()
    assert normalize_result("m").metrics == "m"
    r = normalize_result(("m", ["i"], ["w"], 5))
    assert (r.metrics, r.issues, r.warnings, r.penalty) == ("m", ["i"], ["w"], 5)
    assert normalize_result(("m",)).penalty == 0
    assert normalize_result(("m", None, None, "bad")).penalty == 0
    assert normalize_result(("m", [], [], -3)).penalty == 0


def test_duplicate_name_rejected():
    reg = StageRegistry()
    reg.register(_stage("a"))
    with pytest.raises(DuplicateStageError):
        reg.register(_stage("a"))


def test_order_and_ties():
    reg = StageRegistry()
    reg.register(_stage("c", order=50))
    reg.register(_stage("a", order=10))
    reg.register(_stage("b", order=50))
    assert reg.names() == ["a", "c", "b"]


@run_async
async def test_collects_results_and_applies_metrics():
    reg = StageRegistry()
    reg.register(_stage("x", ("M", ["i1"], ["w1"], 7),
                        apply=lambda ctx, m: ctx.extras.__setitem__("x", m)))
    ctx = await run_stages(reg, _ctx())
    assert ctx.extras["x"] == "M"
    assert ctx.issues == ["i1"] and ctx.warnings == ["w1"]
    assert ctx.score == 93
    assert ctx.report.failed_analyzers == []


@run_async
async def test_failure_isolated_penalized_and_capped():
    async def boom(ctx):
        raise RuntimeError("x")

    reg = StageRegistry()
    reg.register(Stage("bad", boom, order=1))
    reg.register(_stage("ok", (None, ["i"], [], 0), order=2))
    ctx = await run_stages(reg, _ctx())
    assert ctx.report.failed_analyzers == ["bad"]
    assert "i" in ctx.issues and len(ctx.issues) == 2
    assert ctx.score == 70  # 100-10 = 90, capped at 70


@run_async
async def test_enabled_skips_stage():
    reg = StageRegistry()
    reg.register(_stage("skip", ("M", ["i"], [], 50), enabled=lambda c: False))
    ctx = await run_stages(reg, _ctx())
    assert ctx.issues == [] and ctx.score == 100


@run_async
async def test_enabled_error_counts_as_failure():
    def bad(ctx):
        raise ValueError("nope")

    reg = StageRegistry()
    reg.register(_stage("s", enabled=bad))
    ctx = await run_stages(reg, _ctx())
    assert ctx.report.failed_analyzers == ["s"]