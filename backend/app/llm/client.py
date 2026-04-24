"""LiteLLM wrapper: unified LLM interface with multi-model fallback and streaming."""
from __future__ import annotations

import logging
import os
from typing import AsyncIterator

import litellm

from app.config import get_settings
from app.protocols import LLMClient

logger = logging.getLogger(__name__)

# Disable verbose litellm logs
litellm.suppress_debug_info = True


class AllModelsFailedError(Exception):
    """Raised when all models (primary + fallbacks) fail."""

    def __init__(self, errors: list[tuple[str, str]]):
        self.errors = errors
        super().__init__(f"All models failed: {errors}")


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

    async def complete(self, messages: list[dict], **kwargs) -> tuple[str, dict]:
        """Non-streaming generation with fallback. Returns (content, token_usage)."""
        models = [self._resolve_model()] + self._get_fallback_models()
        params = self._resolve_params()
        params.update(kwargs)

        errors: list[tuple[str, str]] = []
        for model in models:
            try:
                response = await litellm.acompletion(model=model, messages=messages, **params)
                content = response.choices[0].message.content or ""
                usage = {
                    "prompt": response.usage.prompt_tokens if response.usage else 0,
                    "completion": response.usage.completion_tokens if response.usage else 0,
                    "total": response.usage.total_tokens if response.usage else 0,
                    "model": model,
                }
                if model != models[0]:
                    logger.info("Fallback succeeded: model=%s (primary=%s failed)", model, models[0])
                return content, usage
            except Exception as e:
                logger.warning("Model %s failed for %s: %s", model, self.task_type, e)
                errors.append((model, str(e)))

        raise AllModelsFailedError(errors)

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        """Streaming generation with fallback. Yields token chunks."""
        models = [self._resolve_model()] + self._get_fallback_models()
        params = self._resolve_params()
        params.update(kwargs)

        errors: list[tuple[str, str]] = []
        for model in models:
            try:
                response = await litellm.acompletion(model=model, messages=messages, stream=True, **params)
                if model != models[0]:
                    logger.info("Fallback stream succeeded: model=%s (primary=%s failed)", model, models[0])
                async for chunk in response:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content
                return
            except Exception as e:
                logger.warning("Model %s stream failed for %s: %s", model, self.task_type, e)
                errors.append((model, str(e)))

        raise AllModelsFailedError(errors)


# Verify implementation satisfies Protocol
assert isinstance(LiteLLMClientImpl(), LLMClient)
