"""LiteLLM wrapper: unified LLM interface with multi-model fallback and streaming."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import AsyncIterator

import litellm

from app.config import get_settings
from app.observability import metrics
from app.protocols import LLMClient

logger = logging.getLogger(__name__)

# Disable verbose litellm logs
litellm.suppress_debug_info = True


class AllModelsFailedError(Exception):
    """Raised when all models (primary + fallbacks) fail."""

    def __init__(self, errors: list[tuple[str, str]]):
        self.errors = errors
        super().__init__(self.user_message)

    @property
    def user_message(self) -> str:
        models = ", ".join(model for model, _ in self.errors)
        if any("auth" in error.lower() or "api key" in error.lower() for _, error in self.errors):
            return f"模型认证失败，请检查后端 .env 中的 API Key 或切换可用模型。失败模型：{models}"
        return f"模型调用失败，所有配置模型均不可用。失败模型：{models}"


def _sanitize_error(error: Exception) -> str:
    """去掉可能包含 key 片段的供应商原始错误，避免透传到前端或日志。"""
    text = str(error)
    if "api key" in text.lower() or "authentication" in text.lower() or "auth" in text.lower():
        return "authentication failed"
    return text


class LiteLLMClientImpl:
    """LLMClient Protocol implementation with config-driven fallback."""

    def __init__(self, model: str | None = None, task_type: str = "general"):
        settings = get_settings()
        self.model = model
        self.task_type = task_type
        self._config = self._load_task_config(settings)
        self._configure_env(settings)

    def _load_task_config(self, settings) -> dict:
        """Load task-specific config from models.yaml."""
        cfg = settings.models_config
        models_cfg = cfg.get("models", {})
        return models_cfg.get(self.task_type, {})

    def _resolve_model(self) -> str:
        """Return the model to use (user override > primary from config > default)."""
        if self.model:
            return self.model
        primary = self._config.get("primary")
        if primary:
            return primary
        return get_settings().default_model

    def _resolve_params(self) -> dict:
        """Return LLM params (temperature, max_tokens) from config."""
        params = {}
        if "temperature" in self._config:
            params["temperature"] = self._config["temperature"]
        if "max_tokens" in self._config:
            params["max_tokens"] = self._config["max_tokens"]
        return params

    def _get_fallback_models(self) -> list[str]:
        """Return fallback model list from config."""
        return list(self._config.get("fallback", []))

    def _configure_env(self, settings) -> None:
        """Inject configured API keys into environment variables (LiteLLM reads from env)."""
        if settings.deepseek_api_key:
            os.environ["DEEPSEEK_API_KEY"] = settings.deepseek_api_key
        if settings.dashscope_api_key:
            os.environ["DASHSCOPE_API_KEY"] = settings.dashscope_api_key
        if settings.openai_api_key:
            os.environ["OPENAI_API_KEY"] = settings.openai_api_key
        if settings.anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key

    async def complete(self, messages: list[dict], **kwargs) -> tuple[str, dict, list[dict] | None]:
        """Non-streaming generation with fallback. Returns (content, token_usage, tool_calls).

        tool_calls is a list of dicts with {id, name, arguments} when the model
        responds with a function call, or None for plain text responses.
        """
        models = [self._resolve_model()] + self._get_fallback_models()
        params = self._resolve_params()
        params.update(kwargs)

        errors: list[tuple[str, str]] = []
        for model in models:
            start = time.perf_counter()
            try:
                response = await litellm.acompletion(model=model, messages=messages, **params)
                msg = response.choices[0].message
                content = msg.content or ""
                # Extract tool_calls if present (model responded with function call)
                tool_calls = None
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    tool_calls = [
                        {
                            "id": tc.id if hasattr(tc, "id") else f"call_{i}",
                            "name": tc.function.name if hasattr(tc, "function") else tc.name,
                            "args": (
                                json.loads(tc.function.arguments)
                                if hasattr(tc, "function") and tc.function.arguments
                                else (tc.arguments if hasattr(tc, "arguments") else {})
                            ),
                        }
                        for i, tc in enumerate(msg.tool_calls)
                    ]
                usage = {
                    "prompt": response.usage.prompt_tokens if response.usage else 0,
                    "completion": response.usage.completion_tokens if response.usage else 0,
                    "total": response.usage.total_tokens if response.usage else 0,
                    "model": model,
                }
                if model != models[0]:
                    logger.info("Fallback succeeded: model=%s (primary=%s failed)", model, models[0])
                metrics.record_llm_call(
                    task_type=self.task_type,
                    model=model,
                    status="ok",
                    latency_seconds=time.perf_counter() - start,
                    prompt_tokens=usage["prompt"],
                    completion_tokens=usage["completion"],
                )
                return content, usage, tool_calls
            except Exception as e:
                error_message = _sanitize_error(e)
                logger.warning("Model %s failed for %s: %s", model, self.task_type, error_message)
                metrics.record_llm_call(
                    task_type=self.task_type,
                    model=model,
                    status="error",
                    latency_seconds=time.perf_counter() - start,
                )
                errors.append((model, error_message))

        raise AllModelsFailedError(errors)

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        """Streaming generation with fallback. Yields token chunks."""
        models = [self._resolve_model()] + self._get_fallback_models()
        params = self._resolve_params()
        params.update(kwargs)

        errors: list[tuple[str, str]] = []
        for model in models:
            start = time.perf_counter()
            try:
                response = await litellm.acompletion(model=model, messages=messages, stream=True, **params)
                if model != models[0]:
                    logger.info("Fallback stream succeeded: model=%s (primary=%s failed)", model, models[0])
                async for chunk in response:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content
                metrics.record_llm_call(
                    task_type=self.task_type,
                    model=model,
                    status="ok",
                    latency_seconds=time.perf_counter() - start,
                )
                return
            except Exception as e:
                error_message = _sanitize_error(e)
                logger.warning("Model %s stream failed for %s: %s", model, self.task_type, error_message)
                metrics.record_llm_call(
                    task_type=self.task_type,
                    model=model,
                    status="error",
                    latency_seconds=time.perf_counter() - start,
                )
                errors.append((model, error_message))

        raise AllModelsFailedError(errors)


# Verify implementation satisfies Protocol
assert isinstance(LiteLLMClientImpl(), LLMClient)
