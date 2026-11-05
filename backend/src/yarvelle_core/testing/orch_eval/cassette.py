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

"""Record and replay model exchanges for orchestration evals.

A cassette stores one model request (normalized messages, tool schemas and
params) keyed by SHA-256, with the response and optional usage. Recording
writes JSONL under ``<root>/<pack>/<scenario>/<backend>-<model>.jsonl``.
Replay serves the stored response and fails clearly on a miss or when the
normalized request no longer matches (prompt or tool-schema drift).

Committed neutral cassettes live under ``backend/evals/orchestration/cassettes/``.
App-specific recordings should use a separate path (``--cassette`` or
``YARVELLE_CASSETTES_DIR``) that stays outside the repo or under a gitignored
``cassettes.local/`` tree. Importing this module never opens a network socket.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import PrivateAttr

from yarvelle_core.testing.orch_eval.backends import FREE, CostTable, Role

# backend/src/yarvelle_core/testing/orch_eval/cassette.py -> parents[4] == backend/
DEFAULT_COMMITTED_CASSETTES = Path(__file__).resolve().parents[4] / "evals" / "orchestration" / "cassettes"


class CassetteError(RuntimeError):
    """Base error for record/replay problems."""


class CassetteMissError(CassetteError):
    """Raised when replay cannot find a matching request."""

    def __init__(self, message: str, *, request: Mapping[str, Any], key: str) -> None:
        super().__init__(message)
        self.request = dict(request)
        self.key = key


def default_cassette_root() -> Path:
    """Committed neutral cassettes, or ``YARVELLE_CASSETTES_DIR`` when set."""
    override = os.environ.get("YARVELLE_CASSETTES_DIR")
    if override:
        return Path(override).expanduser()
    return DEFAULT_COMMITTED_CASSETTES


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "model"


def cassette_path(
    root: Path,
    *,
    pack: str,
    scenario: str,
    backend: str,
    model: str,
) -> Path:
    return root / _slug(pack) / _slug(scenario) / f"{_slug(backend)}-{_slug(model)}.jsonl"


_HOME = str(Path.home())
_USER = os.environ.get("USER") or os.environ.get("USERNAME") or ""


def sanitize_text(value: str) -> str:
    """Strips machine-local paths and usernames from recorded text."""
    text = value
    if _HOME:
        text = text.replace(_HOME, "~")
    # Common absolute workspace prefixes on this fleet.
    text = re.sub(r"/Users/[^/\s]+", "/Users/<user>", text)
    text = re.sub(r"/home/[^/\s]+", "/home/<user>", text)
    if _USER and len(_USER) > 2:
        text = re.sub(rf"\b{re.escape(_USER)}\b", "<user>", text)
    return text


def _normalize_content(content: Any) -> Any:
    if isinstance(content, str):
        return sanitize_text(content)
    if isinstance(content, list):
        return [_normalize_content(part) for part in content]
    if isinstance(content, Mapping):
        return {str(k): _normalize_content(v) for k, v in sorted(content.items(), key=lambda kv: str(kv[0]))}
    return content


def normalize_messages(messages: Sequence[BaseMessage]) -> List[Dict[str, Any]]:
    """Canonical message list for hashing (no ids, no timestamps)."""
    out: List[Dict[str, Any]] = []
    for msg in messages:
        item: Dict[str, Any] = {
            "type": getattr(msg, "type", type(msg).__name__),
            "content": _normalize_content(getattr(msg, "content", "")),
        }
        tool_calls = getattr(msg, "tool_calls", None) or []
        if tool_calls:
            item["tool_calls"] = [
                {
                    "name": c.get("name"),
                    "args": _normalize_content(c.get("args") or {}),
                }
                for c in tool_calls
            ]
        if isinstance(msg, ToolMessage) or getattr(msg, "type", "") == "tool":
            item["name"] = getattr(msg, "name", None)
        out.append(item)
    return out


def normalize_tools(tools: Optional[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Canonical tool schemas (name + parameters only)."""
    if not tools:
        return []
    out: List[Dict[str, Any]] = []
    for tool in tools:
        if isinstance(tool, Mapping):
            name = tool.get("name") or (tool.get("function") or {}).get("name")
            params = tool.get("parameters") or (tool.get("function") or {}).get("parameters") or {}
            out.append({"name": name, "parameters": _normalize_content(params)})
            continue
        name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
        schema: Any = None
        if hasattr(tool, "args_schema") and tool.args_schema is not None:
            try:
                schema = tool.args_schema.model_json_schema()
            except Exception:
                schema = getattr(tool, "schema", None)
        elif hasattr(tool, "tool_call_schema"):
            schema = tool.tool_call_schema
        out.append({"name": name, "parameters": _normalize_content(schema or {})})
    out.sort(key=lambda t: str(t.get("name") or ""))
    return out


def request_fingerprint(
    messages: Sequence[BaseMessage],
    *,
    tools: Optional[Sequence[Any]] = None,
    params: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Returns ``(sha256, canonical_request)``."""
    payload = {
        "messages": normalize_messages(messages),
        "tools": normalize_tools(tools),
        "params": {str(k): params[k] for k in sorted(params or {})},
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), payload


def _message_from_response(response: Mapping[str, Any]) -> AIMessage:
    content = response.get("content") or ""
    tool_calls = response.get("tool_calls") or []
    kwargs: Dict[str, Any] = {"content": content}
    if tool_calls:
        kwargs["tool_calls"] = [
            {
                "name": c["name"],
                "args": c.get("args") or {},
                "id": c.get("id") or f"replay-{i}",
                "type": "tool_call",
            }
            for i, c in enumerate(tool_calls)
        ]
    return AIMessage(**kwargs)


def _message_text(message: BaseMessage) -> str:
    """Best-effort plain text from a chat message.

    Some local models (for example Qwen3 with thinking enabled) return token
    usage with an empty ``content`` while the usable reply sits under
    ``additional_kwargs`` / response metadata. Prefer ``content``, then fall
    back so a recording is still useful.
    """
    content = getattr(message, "content", None)
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, Mapping):
                text = part.get("text") or part.get("content") or part.get("thinking") or ""
                if text:
                    parts.append(str(text))
        joined = "".join(parts).strip()
        if joined:
            return joined
    additional = getattr(message, "additional_kwargs", None) or {}
    if isinstance(additional, Mapping):
        for key in ("content", "text", "thinking", "reasoning_content"):
            value = additional.get(key)
            if isinstance(value, str) and value.strip():
                return value
    meta = getattr(message, "response_metadata", None) or {}
    if isinstance(meta, Mapping):
        for key in ("thinking", "reasoning_content", "content"):
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return str(content or "")


def _response_from_message(message: BaseMessage) -> Dict[str, Any]:
    tool_calls = getattr(message, "tool_calls", None) or []
    return {
        "content": sanitize_text(_message_text(message)),
        "tool_calls": [
            {
                "name": c.get("name"),
                "args": _normalize_content(c.get("args") or {}),
                "id": c.get("id"),
            }
            for c in tool_calls
        ],
    }


@dataclass
class CassetteStore:
    """In-memory index over one or more JSONL cassette files."""

    entries: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    path: Optional[Path] = None
    dirty: bool = False

    @classmethod
    def load(cls, path: Path) -> "CassetteStore":
        store = cls(path=path)
        if not path.is_file():
            return store
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            key = str(entry.get("key") or "")
            if key:
                store.entries[key] = entry
        return store

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self.entries.get(key)

    def put(self, entry: Mapping[str, Any]) -> None:
        key = str(entry.get("key") or "")
        if not key:
            raise CassetteError("cassette entry needs a key")
        self.entries[key] = dict(entry)
        self.dirty = True

    def save(self) -> None:
        if self.path is None:
            raise CassetteError("cassette store has no path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(self.entries[k], sort_keys=True, ensure_ascii=False, default=str)
            for k in sorted(self.entries)
        ]
        self.path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        self.dirty = False

    def nearest_request(self, request: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        """Best-effort match for miss diagnostics (same message count)."""
        want = (request.get("messages") or [])
        best = None
        best_score = -1
        for entry in self.entries.values():
            got = (entry.get("request") or {}).get("messages") or []
            if len(got) != len(want):
                continue
            score = sum(1 for a, b in zip(want, got) if a == b)
            if score > best_score:
                best_score = score
                best = entry.get("request")
        return best


class CassetteChatModel(BaseChatModel):
    """Chat model that records or replays through a :class:`CassetteStore`."""

    inner: Any = None
    mode: str = "replay"  # record | replay
    _store: CassetteStore = PrivateAttr(default_factory=CassetteStore)
    _tools: List[Any] = PrivateAttr(default_factory=list)
    _params: Dict[str, Any] = PrivateAttr(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}

    def __init__(
        self,
        *,
        store: CassetteStore,
        mode: str = "replay",
        inner: Any = None,
        tools: Optional[Sequence[Any]] = None,
        params: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        if mode not in ("record", "replay"):
            raise ValueError(f"unknown cassette mode {mode!r}")
        if mode == "record" and inner is None:
            raise ValueError("record mode needs an inner chat model")
        super().__init__(inner=inner, mode=mode, **kwargs)
        self._store = store
        self._tools = list(tools or [])
        self._params = dict(params or {})

    @property
    def _llm_type(self) -> str:
        return f"orch-eval-cassette-{self.mode}"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "CassetteChatModel":
        bound_inner = self.inner
        if self.inner is not None and hasattr(self.inner, "bind_tools"):
            bound_inner = self.inner.bind_tools(tools, **kwargs)
        clone = CassetteChatModel(
            store=self._store,
            mode=self.mode,
            inner=bound_inner,
            tools=tools,
            params=self._params,
        )
        return clone

    def _lookup_or_call_sync(self, messages: List[BaseMessage]) -> AIMessage:
        key, request = request_fingerprint(messages, tools=self._tools, params=self._params)
        if self.mode == "replay":
            entry = self._store.get(key)
            if entry is None:
                nearest = self._store.nearest_request(request)
                hint = ""
                if nearest is not None:
                    hint = f" Nearest stored request had {len(nearest.get('messages') or [])} message(s)."
                raise CassetteMissError(
                    f"cassette stale: prompt or tool schema changed (key {key[:12]}…).{hint}",
                    request=request,
                    key=key,
                )
            return _message_from_response(entry.get("response") or {})

        if hasattr(self.inner, "invoke"):
            # Prefer public invoke so provider streaming/bindings work.
            result = self.inner.invoke(messages)
            message = result if isinstance(result, BaseMessage) else result
        else:
            result = self.inner._generate(messages)
            message = result.generations[0].message
        self._store.put(
            {
                "key": key,
                "request": request,
                "response": _response_from_message(message),
                "usage": _usage(message),
            }
        )
        return message if isinstance(message, AIMessage) else AIMessage(content=str(getattr(message, "content", "")))

    async def _lookup_or_call_async(self, messages: List[BaseMessage]) -> AIMessage:
        key, request = request_fingerprint(messages, tools=self._tools, params=self._params)
        if self.mode == "replay":
            entry = self._store.get(key)
            if entry is None:
                nearest = self._store.nearest_request(request)
                hint = ""
                if nearest is not None:
                    hint = f" Nearest stored request had {len(nearest.get('messages') or [])} message(s)."
                raise CassetteMissError(
                    f"cassette stale: prompt or tool schema changed (key {key[:12]}…).{hint}",
                    request=request,
                    key=key,
                )
            return _message_from_response(entry.get("response") or {})

        if hasattr(self.inner, "ainvoke"):
            message = await self.inner.ainvoke(messages)
        elif hasattr(self.inner, "_agenerate"):
            result = await self.inner._agenerate(messages)
            message = result.generations[0].message
        else:
            message = self._lookup_or_call_sync(messages)
            return message
        self._store.put(
            {
                "key": key,
                "request": request,
                "response": _response_from_message(message),
                "usage": _usage(message),
            }
        )
        return message if isinstance(message, AIMessage) else AIMessage(content=str(getattr(message, "content", "")))

    def _generate(
        self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._lookup_or_call_sync(messages))])

    async def _agenerate(
        self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=await self._lookup_or_call_async(messages))])

    async def _astream(
        self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        msg = await self._lookup_or_call_async(messages)
        calls = getattr(msg, "tool_calls", None) or []
        chunk = AIMessageChunk(
            content=msg.content,
            tool_call_chunks=[
                {
                    "name": c["name"],
                    "args": json.dumps(c["args"]),
                    "id": c["id"],
                    "index": i,
                    "type": "tool_call_chunk",
                }
                for i, c in enumerate(calls)
            ],
        )
        yield ChatGenerationChunk(message=chunk)


def _usage(message: BaseMessage) -> Dict[str, int]:
    meta = getattr(message, "usage_metadata", None) or {}
    if isinstance(meta, Mapping):
        return {
            "input_tokens": int(meta.get("input_tokens") or meta.get("input") or 0),
            "output_tokens": int(meta.get("output_tokens") or meta.get("output") or 0),
        }
    return {"input_tokens": 0, "output_tokens": 0}


class CassetteBackend:
    """Eval backend that records through an inner backend or replays from disk."""

    name = "replay"
    cost_per_mtok: CostTable = FREE

    def __init__(
        self,
        *,
        cassette_root: Path,
        mode: str = "replay",
        inner: Any = None,
        backend_label: str = "replay",
        model_label: str = "cassette",
        pack_id: str = "eval-neutral",
        scenario_id: str = "unknown",
    ) -> None:
        if mode not in ("record", "replay"):
            raise ValueError(f"unknown cassette mode {mode!r}")
        if mode == "record" and inner is None:
            raise ValueError("record mode needs an inner backend")
        self.mode = mode
        self.cassette_root = Path(cassette_root)
        self.inner = inner
        self.backend_label = backend_label
        self.model_label = model_label
        self.pack_id = pack_id
        self.scenario_id = scenario_id
        self._stores: Dict[Path, CassetteStore] = {}
        self._models: Dict[str, CassetteChatModel] = {}
        if mode == "record":
            self.name = getattr(inner, "name", backend_label)

    def begin_scenario(self, *, pack_id: str, scenario_id: str) -> None:
        self.pack_id = pack_id
        self.scenario_id = scenario_id
        self._models.clear()

    def set_agents(self, agent_ids: Iterable[str]) -> None:
        if self.inner is not None and hasattr(self.inner, "set_agents"):
            self.inner.set_agents(agent_ids)

    def _path(self) -> Path:
        return cassette_path(
            self.cassette_root,
            pack=self.pack_id,
            scenario=self.scenario_id,
            backend=self.backend_label,
            model=self.model_label,
        )

    def _store(self) -> CassetteStore:
        path = self._path()
        store = self._stores.get(path)
        if store is None:
            store = CassetteStore.load(path)
            self._stores[path] = store
        return store

    def model_for(self, role: Role) -> Any:
        key = "judge" if role.kind == "judge" else "subject"
        if key in self._models:
            return self._models[key]
        store = self._store()
        if self.mode == "record":
            inner_model = self.inner.model_for(role)
            model = CassetteChatModel(store=store, mode="record", inner=inner_model)
        else:
            if not store.entries and not self._path().is_file():
                raise CassetteError(
                    f"no cassette for {self.pack_id}/{self.scenario_id} "
                    f"({self.backend_label}-{self.model_label}) under {self.cassette_root}"
                )
            model = CassetteChatModel(store=store, mode="replay", inner=None)
        self._models[key] = model
        return model

    def flush(self) -> List[Path]:
        """Persists dirty stores. Returns paths written."""
        written: List[Path] = []
        for store in self._stores.values():
            if store.dirty and store.path is not None:
                store.save()
                written.append(store.path)
        return written

    def describe(self) -> dict[str, Any]:
        desc: Dict[str, Any] = {
            "backend": "replay" if self.mode == "replay" else self.backend_label,
            "cassette_mode": self.mode,
            "cassette_root": str(self.cassette_root),
            "cassette_backend": self.backend_label,
            "cassette_model": self.model_label,
            "pack": self.pack_id,
            "scenario": self.scenario_id,
        }
        if self.inner is not None and hasattr(self.inner, "describe"):
            desc["inner"] = self.inner.describe()
            # Prefer subject model from the live backend when recording.
            inner_desc = desc["inner"]
            if isinstance(inner_desc, Mapping):
                desc["subject_model"] = inner_desc.get("subject_model") or inner_desc.get("model")
        if self.mode == "replay":
            desc["subject_model"] = self.model_label
            desc["model"] = self.model_label
        return desc


__all__ = [
    "DEFAULT_COMMITTED_CASSETTES",
    "CassetteBackend",
    "CassetteChatModel",
    "CassetteError",
    "CassetteMissError",
    "CassetteStore",
    "cassette_path",
    "default_cassette_root",
    "normalize_messages",
    "normalize_tools",
    "request_fingerprint",
    "sanitize_text",
]
