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


"""Unit tests for orchestration eval cassette record/replay."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from yarvelle_core.testing.orch_eval.backends import Role
from yarvelle_core.testing.orch_eval.cassette import (
    CassetteBackend,
    CassetteChatModel,
    CassetteError,
    CassetteMissError,
    CassetteStore,
    cassette_path,
    default_cassette_root,
    normalize_messages,
    request_fingerprint,
    sanitize_text,
)


class _ScriptedInner:
    """Minimal sync chat model stand-in for record tests."""

    def __init__(self, replies: List[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    def invoke(self, messages: List[Any], **kwargs: Any) -> AIMessage:
        self.calls += 1
        if not self.replies:
            raise AssertionError("scripted inner exhausted")
        return AIMessage(content=self.replies.pop(0))

    def bind_tools(self, tools, **kwargs):
        return self


class _ScriptedBackend:
    name = "ollama"
    cost_per_mtok = None

    def __init__(self, replies: List[str]) -> None:
        self._inner = _ScriptedInner(replies)

    def model_for(self, role: Role) -> Any:
        return self._inner

    def describe(self) -> dict:
        return {"backend": "ollama", "subject_model": "qwen3:8b"}


def test_sanitize_text_strips_home_and_username(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("USER", "alice")
    # Re-import sanitize helpers would keep module-level _USER; call with patched constants.
    from yarvelle_core.testing.orch_eval import cassette as mod

    monkeypatch.setattr(mod, "_HOME", "/Users/alice")
    monkeypatch.setattr(mod, "_USER", "alice")
    text = sanitize_text("see /Users/alice/git/x and alice wrote this")
    assert "/Users/<user>" in text or "~" in text
    assert "alice" not in text.replace("<user>", "")


def test_request_fingerprint_stable_and_order_independent_for_tools():
    msgs = [SystemMessage(content="sys"), HumanMessage(content="hi")]
    k1, p1 = request_fingerprint(msgs, tools=[{"name": "b", "parameters": {}}, {"name": "a", "parameters": {}}])
    k2, p2 = request_fingerprint(msgs, tools=[{"name": "a", "parameters": {}}, {"name": "b", "parameters": {}}])
    assert k1 == k2
    assert [t["name"] for t in p1["tools"]] == ["a", "b"]


def test_cassette_store_roundtrip(tmp_path: Path):
    path = tmp_path / "pack" / "scen" / "ollama-qwen3-8b.jsonl"
    store = CassetteStore(path=path)
    key, req = request_fingerprint([HumanMessage(content="hello")])
    store.put({"key": key, "request": req, "response": {"content": "hi", "tool_calls": []}, "usage": {}})
    store.save()
    loaded = CassetteStore.load(path)
    assert loaded.get(key)["response"]["content"] == "hi"


def test_record_then_replay_chat_model(tmp_path: Path):
    path = tmp_path / "c.jsonl"
    store = CassetteStore(path=path)
    inner = _ScriptedInner(["hello there"])
    recorder = CassetteChatModel(store=store, mode="record", inner=inner)
    msgs = [HumanMessage(content="Hi there!")]
    out = recorder.invoke(msgs)
    assert out.content == "hello there"
    assert inner.calls == 1
    store.save()

    replay_store = CassetteStore.load(path)
    player = CassetteChatModel(store=replay_store, mode="replay", inner=None)
    out2 = player.invoke(msgs)
    assert out2.content == "hello there"

    with pytest.raises(CassetteMissError) as exc:
        player.invoke([HumanMessage(content="different prompt")])
    assert "stale" in str(exc.value).lower() or "changed" in str(exc.value).lower()


def test_cassette_backend_record_flush_and_replay(tmp_path: Path):
    root = tmp_path / "cassettes"
    inner = _ScriptedBackend(["ok"])
    be = CassetteBackend(
        cassette_root=root,
        mode="record",
        inner=inner,
        backend_label="ollama",
        model_label="qwen3:8b",
    )
    be.begin_scenario(pack_id="eval-neutral", scenario_id="live-smoke-greeting")
    model = be.model_for(Role(kind="main"))
    msg = model.invoke([HumanMessage(content="Hi there!")])
    assert msg.content == "ok"
    written = be.flush()
    assert len(written) == 1
    assert written[0].is_file()

    replay = CassetteBackend(
        cassette_root=root,
        mode="replay",
        inner=None,
        backend_label="ollama",
        model_label="qwen3:8b",
    )
    replay.begin_scenario(pack_id="eval-neutral", scenario_id="live-smoke-greeting")
    model2 = replay.model_for(Role(kind="main"))
    assert model2.invoke([HumanMessage(content="Hi there!")]).content == "ok"
    assert replay.describe()["backend"] == "replay"


def test_replay_missing_cassette_raises(tmp_path: Path):
    be = CassetteBackend(
        cassette_root=tmp_path,
        mode="replay",
        backend_label="ollama",
        model_label="qwen3:8b",
    )
    be.begin_scenario(pack_id="eval-neutral", scenario_id="missing")
    with pytest.raises(CassetteError):
        be.model_for(Role(kind="main"))


def test_default_cassette_root_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("YARVELLE_CASSETTES_DIR", str(tmp_path / "local"))
    assert default_cassette_root() == tmp_path / "local"


def test_cassette_path_slugs_model():
    path = cassette_path(
        Path("/tmp/c"),
        pack="eval-neutral",
        scenario="live-smoke-greeting",
        backend="ollama",
        model="qwen3:8b",
    )
    assert path.name == "ollama-qwen3-8b.jsonl"
    assert "live-smoke-greeting" in str(path)


def test_normalize_messages_drops_ids():
    msg = AIMessage(content="x", id="abc")
    norm = normalize_messages([msg])
    assert "id" not in norm[0]
