"""Audit pipeline: an explicit, ordered registry of analysis stages.

A *stage* is an async callable ``run(ctx) -> StageResult | tuple | None``.
The runner isolates failures (one broken stage never aborts the audit),
applies score penalties, and collects issues/warnings in registration order.

Registration is explicit (no auto-discovery) so execution order is
deterministic and safe. This module is self-contained: it does not import
the engine, so the engine can import it without circular dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("seo_core.pipeline")

STAGE_FAILURE_PENALTY = 10
INCOMPLETE_AUDIT_SCORE_CAP = 70


class DuplicateStageError(ValueError):
    """Raised when a stage name is registered twice."""


@dataclass
class StageResult:
    """Normalized output of a stage."""

    metrics: Any = None
    issues: List[Any] = field(default_factory=list)
    warnings: List[Any] = field(default_factory=list)
    penalty: int = 0


@dataclass
class AuditContext:
    """Shared mutable state passed to every stage."""

    url: str
    html: str = ""
    client: Any = None
    report: Any = None
    local_business: Optional[bool] = None
    score: int = 100
    issues: List[Any] = field(default_factory=list)
    warnings: List[Any] = field(default_factory=list)
    extras: Dict[str, Any] = field(default_factory=dict)


StageFunc = Callable[[AuditContext], Awaitable[Any]]
ApplyFunc = Callable[[AuditContext, Any], None]
EnabledFunc = Callable[[AuditContext], bool]


@dataclass(frozen=True)
class Stage:
    """One analysis step.

    ``apply`` receives the stage's metrics and stores them on the report.
    ``enabled`` may skip the stage based on context.
    """

    name: str
    run: StageFunc
    apply: Optional[ApplyFunc] = None
    enabled: Optional[EnabledFunc] = None
    order: int = 100


def normalize_result(res: Any) -> StageResult:
    """Accept StageResult, None, a bare metrics object, or a 1-4 tuple."""
    if res is None:
        return StageResult()
    if isinstance(res, StageResult):
        return res
    if not isinstance(res, tuple):
        return StageResult(metrics=res)

    metrics = res[0] if len(res) >= 1 else None
    issues = list(res[1] or []) if len(res) >= 2 else []
    warnings = list(res[2] or []) if len(res) >= 3 else []
    penalty = 0
    if len(res) >= 4:
        try:
            penalty = max(0, int(res[3] or 0))
        except (TypeError, ValueError):
            logger.warning("Invalid stage penalty ignored: %r", res[3])
    return StageResult(metrics, issues, warnings, penalty)


class StageRegistry:
    """Ordered collection of stages. Ties keep registration order."""

    def __init__(self) -> None:
        self._stages: List[Stage] = []

    def register(self, stage: Stage) -> Stage:
        if any(s.name == stage.name for s in self._stages):
            raise DuplicateStageError(f"Stage already registered: {stage.name}")
        self._stages.append(stage)
        return stage

    def ordered(self) -> List[Stage]:
        # sorted() is stable: equal order values keep registration order
        return sorted(self._stages, key=lambda s: s.order)

    def names(self) -> List[str]:
        return [s.name for s in self.ordered()]

    def __len__(self) -> int:
        return len(self._stages)


async def run_stages(registry: StageRegistry, ctx: AuditContext) -> AuditContext:
    """Run all enabled stages in order, isolating failures."""
    failed: List[str] = []

    for stage in registry.ordered():
        try:
            if stage.enabled is not None and not stage.enabled(ctx):
                continue
            result = normalize_result(await stage.run(ctx))
            if stage.apply is not None and result.metrics is not None:
                stage.apply(ctx, result.metrics)
            ctx.issues.extend(result.issues)
            ctx.warnings.extend(result.warnings)
            ctx.score = max(0, ctx.score - result.penalty)
        except Exception as err:  # boundary: one stage must not abort the audit
            logger.warning("%s analysis error: %s", stage.name, err, exc_info=True)
            failed.append(stage.name)
            ctx.issues.append(
                f"تحلیل «{stage.name}» با خطا متوقف شد و بررسی ناقص ماند ({type(err).__name__})."
            )
            ctx.score = max(0, ctx.score - STAGE_FAILURE_PENALTY)

    if failed:
        if ctx.report is not None and hasattr(ctx.report, "failed_analyzers"):
            ctx.report.failed_analyzers.extend(failed)
        ctx.score = min(ctx.score, INCOMPLETE_AUDIT_SCORE_CAP)
    return ctx