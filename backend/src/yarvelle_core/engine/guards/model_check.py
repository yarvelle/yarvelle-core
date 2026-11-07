# Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Model guard checks (``type: model``).

The model is any LangChain ``BaseChatModel``. Core builds it with
``yarvelle_core.model.factory.create_chat_model`` from the check's endpoint
(pack ``model`` block plus environment overrides), exactly like the agent
models, so Ollama, OpenAI-compatible servers and hosted providers all work
and the egress policy applies. A caller can also pass a ready model (tests,
or an in-process classifier wrapped as a chat model).

Two ways to ask:

- ``moderation``: the conversation as chat messages (optional system
  message, the user's message, then the answer being checked). Guard models
  such as Llama Guard or Granite Guardian apply their own chat template.
- ``prompt``: one user message built from the pack's template, for a
  self-trained classifier behind a chat endpoint or a judge prompt.

Text longer than ``max_chars`` is not truncated; the check abstains. Model
tokens never reach the user stream: calls are tagged ``internal`` and
``no_stream`` and run without streaming.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Callable, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from yarvelle_core.engine.guards.env import resolve_endpoint, resolve_mode, resolve_timeout
from yarvelle_core.engine.guards.parsing import parse_reply, reply_text
from yarvelle_core.engine.guards.presets import resolve_style_and_output
from yarvelle_core.engine.guards.types import GuardDecision, GuardRequest, GuardResult
from yarvelle_core.logging import get_logger
from yarvelle_core.schemas.safety import GuardCheckSpec

logger = get_logger("yarvelle_core.engine.guards")

GUARD_RUN_TAGS = ["internal", "no_stream", "safety_guard"]

ModelFactory = Callable[..., Any]


class ModelCheckConfigError(ValueError):
    """A model check is declared inconsistently."""


def _default_factory(**kwargs: Any) -> Any:
    from yarvelle_core.model.factory import create_chat_model

    return create_chat_model(**kwargs)


def render_template(template: str, *, text: str, prompt: str, stage: str) -> str:
    return template.replace("{{text}}", text).replace("{{prompt}}", prompt).replace("{{stage}}", stage)


class ModelCheck:
    """A ``model`` check bound to a lazily built chat model."""

    kind = "model"

    def __init__(
        self,
        spec: GuardCheckSpec,
        *,
        chat_model: Any = None,
        model_factory: Optional[ModelFactory] = None,
        prompt_template: Optional[str] = None,
    ) -> None:
        self.spec = spec
        self.id = spec.id
        self.mode = resolve_mode(spec)
        self.style, self.output = resolve_style_and_output(spec)
        self.template = prompt_template if prompt_template is not None else spec.prompt
        if self.style == "prompt" and not (self.template and self.template.strip()):
            raise ModelCheckConfigError(f"model check '{self.id}' uses style prompt but has no prompt template")
        self.timeout_s = resolve_timeout(spec)
        self.endpoint = resolve_endpoint(spec)
        self._factory = model_factory or _default_factory
        self._model = chat_model
        self._model_error: Optional[str] = None
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return self._model is not None or bool(self.endpoint.provider and self.endpoint.model)

    @property
    def model_label(self) -> Optional[str]:
        if self.endpoint.provider and self.endpoint.model:
            return f"{self.endpoint.provider}:{self.endpoint.model}"
        if self._model is not None:
            return type(self._model).__name__
        return None

    def _build_model(self) -> Any:
        if self._model is not None:
            return self._model
        if self._model_error is not None:
            raise RuntimeError(self._model_error)
        kwargs: dict[str, Any] = {
            "provider": self.endpoint.provider,
            "model": self.endpoint.model,
            "temperature": self.endpoint.temperature,
            "timeout": self.timeout_s,
            "streaming": False,
        }
        if self.endpoint.base_url:
            kwargs["base_url"] = self.endpoint.base_url
        try:
            self._model = self._factory(**kwargs)
        except Exception as err:
            # Keep the class name only; messages can carry endpoints or keys.
            self._model_error = f"model_unavailable:{type(err).__name__}"
            logger.warning("safety_guard_model_unavailable", check_id=self.id, error=type(err).__name__)
            raise RuntimeError(self._model_error) from err
        return self._model

    def messages_for(self, request: GuardRequest) -> List[BaseMessage]:
        prompt = request.prompt or ""
        messages: List[BaseMessage] = []
        if self.spec.system:
            messages.append(SystemMessage(content=self.spec.system))
        if self.style == "prompt":
            body = render_template(self.template or "", text=request.text, prompt=prompt, stage=request.stage)
            messages.append(HumanMessage(content=body))
            return messages
        if request.stage == "output" and self.spec.include_prompt and prompt:
            messages.append(HumanMessage(content=prompt))
            messages.append(AIMessage(content=request.text))
        else:
            messages.append(HumanMessage(content=request.text))
        return messages

    def _result(self, decision: GuardDecision, start: float, **kw: Any) -> GuardResult:
        return GuardResult(
            check_id=self.id,
            decision=decision,
            mode=self.mode,
            latency_ms=(time.perf_counter() - start) * 1000.0,
            model=self.model_label,
            **kw,
        )

    async def evaluate(self, request: GuardRequest) -> GuardResult:
        start = time.perf_counter()
        if not self.configured:
            return self._result(GuardDecision.SKIPPED, start, detail="not_configured")
        size = len(request.text or "") + (len(request.prompt or "") if self.spec.include_prompt else 0)
        if size > self.spec.max_chars:
            return self._result(GuardDecision.ABSTAIN, start, detail="text_too_long")
        try:
            with self._lock:
                model = self._build_model()
        except RuntimeError as err:
            return self._result(GuardDecision.ERROR, start, detail=str(err))
        config = {"tags": list(GUARD_RUN_TAGS), "run_name": f"safety_guard:{self.id}"}
        try:
            reply = await asyncio.wait_for(model.ainvoke(self.messages_for(request), config=config), self.timeout_s)
        except asyncio.TimeoutError:
            return self._result(GuardDecision.ERROR, start, detail="timeout")
        except asyncio.CancelledError:
            raise
        except Exception as err:
            logger.warning("safety_guard_call_failed", check_id=self.id, error=type(err).__name__)
            return self._result(GuardDecision.ERROR, start, detail=f"call_failed:{type(err).__name__}")
        parsed = parse_reply(reply_text(getattr(reply, "content", reply)), self.output)
        category = parsed.categories[0] if parsed.categories else None
        return self._result(
            parsed.decision, start, category=category, categories=parsed.categories,
            detail=parsed.detail, score=parsed.score,
        )


__all__ = ["GUARD_RUN_TAGS", "ModelCheck", "ModelCheckConfigError", "render_template"]
