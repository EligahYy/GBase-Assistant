"""可观测性模块：指标埋点收集（暂不暴露 /metrics，待 Phase 3.5.4 决定）。"""

from app.observability.metrics import metrics

__all__ = ["metrics"]
