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

"""Safety guard checks (``safety.guards``): rules, model checks, aggregation.

Every model here is an in-process fake. Nothing calls Ollama or a hosted
provider.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ValidationError

from yarvelle_core.engine.guards import (
    GuardConfigError,
    GuardDecision,
    GuardedSafetyPolicy,
    GuardEnvError,
    GuardRequest,
    ModelCheck,
    RuleCheck,
    RulesConfigError,
    add_guard_audit_hook,
    apply_env_guards,
    build_guarded_policy,
    remove_guard_audit_hook,
)
from yarvelle_core.engine.guards.env import env_only_checks, resolve_endpoint
from yarvelle_core.engine.guards.model_check import GUARD_RUN_TAGS
from yarvelle_core.engine.guards.parsing import parse_reply
from yarvelle_core.engine.guards.policy import SYNC_CALL_REASON
from yarvelle_core.engine.safety_policy import (
    NeutralSafetyPolicy,
    SafetyContext,
    SafetyVerdict,
    UnionSafetyPolicy,
    acheck_input,
    acheck_output,
)
from yarvelle_core.pack.spec import PackManifest, PackSpec
from yarvelle_core.schemas.safety import GuardCheckSpec, ModelOutputSpec, SafetyGuardsSpec
from yarvelle_core.workflows.nodes import InputGuardrailNode, OutputGuardrailNode


# ---------------------------------------------------------------- helpers


class FakeGuardModel(BaseChatModel):
    """Scripted chat model that records what it was asked."""

    replies: List[str] = []
    delay_s: float = 0.0
    fail: bool = False
    calls: List[List[BaseMessage]] = []
    tags_seen: List[List[str]] = []

    @property
    def _llm_type(self) -> str:
        return "fake-guard"

    def _generate(self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any) -> ChatResult:
        raise NotImplementedError("guards call the model asynchronously")

    async def _agenerate(self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any) -> ChatResult:
        self.calls.append(list(messages))
        if run_manager is not None:
            self.tags_seen.append(list(getattr(run_manager, "tags", []) or []))
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.fail:
            raise ConnectionError("endpoint down")
        text = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)] if self.replies else ""
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


def fake(*replies: str, **kw: Any) -> FakeGuardModel:
    return FakeGuardModel(replies=list(replies), calls=[], tags_seen=[], **kw)


class RefuseWord(NeutralSafetyPolicy):
    """A base policy that refuses any text containing 'forbidden'."""

    def __init__(self) -> None:
        self.calls: List[Any] = []

    def check_output(self, text: Optional[str], ctx: Optional[SafetyContext] = None) -> SafetyVerdict:
        self.calls.append(("output", text, ctx))
        if text and "forbidden" in text:
            return SafetyVerdict(refused=True, reason="policy:forbidden", is_hard=True)
        return SafetyVerdict(refused=False)

    def check_input(self, text: Optional[str], ctx: Optional[SafetyContext] = None) -> SafetyVerdict:
        self.calls.append(("input", text, ctx))
        return SafetyVerdict(refused=False)

    def check_flags(self, text: Optional[str], ctx: Optional[SafetyContext] = None) -> List[str]:
        return ["noted"] if text and "note" in text else []


RULES = {
    "id": "secrets",
    "type": "rules",
    "blocks": {"VERB": ["share", "reveal"], "OBJ": "(?:the|your) (?:password|passcode)"},
    "normalize": [{"pattern": r"[*_`]", "replace": ""}],
    "exempt": [r"\bnever <VERB> <OBJ>\b"],
    "patterns": [
        {"id": "reveal", "category": "credential_disclosure", "pattern": r"\b<VERB> <OBJ>\b"},
        {"id": "starts-with-send", "pattern": r"^send it now", "scope": "sentence"},
    ],
}


def model_check(check_id: str = "judge", **over: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {"id": check_id, "type": "model", "preset": "llama_guard"}
    data.update(over)
    return data


def guarded(base: Any = None, checks: Optional[List[Dict[str, Any]]] = None, **kw: Any) -> GuardedSafetyPolicy:
    policy = build_guarded_policy(base or NeutralSafetyPolicy(), {"checks": checks or []}, include_env=False, **kw)
    assert isinstance(policy, GuardedSafetyPolicy)
    return policy


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for name in list(os.environ):
        if "SAFETY_GUARD" in name:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("YARVELLE_ENV_PREFIX", raising=False)


# ---------------------------------------------------------------- config validation


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"id": "r", "type": "rules"}, "needs patterns or rules_file"),
        ({**RULES, "preset": "llama_guard"}, "cannot set model fields"),
        ({**RULES, "exempt": ["("]}, "invalid exempt regex"),
        ({**RULES, "blocks": {"lower": "x"}}, "UPPER_SNAKE_CASE"),
        (model_check(patterns=[{"id": "p", "pattern": "x"}]), "cannot set rules fields"),
        (model_check(style="prompt"), "needs prompt or prompt_file"),
        (model_check(prompt="a", prompt_file="resources/p.md"), "not both"),
        ({"id": "Bad Id", "type": "rules", "patterns": [{"id": "p", "pattern": "x"}]}, "id"),
        ({**RULES, "stages": []}, "stages must not be empty"),
    ],
)
def test_invalid_check_specs_are_rejected(bad: Dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        GuardCheckSpec.model_validate(bad)


def test_duplicate_ids_and_overlapping_labels_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate guard check id"):
        SafetyGuardsSpec.model_validate({"checks": [RULES, RULES]})
    with pytest.raises(ValidationError, match="both allow and block"):
        ModelOutputSpec(allow_labels=["ok"], block_labels=["OK"])
    with pytest.raises(ValidationError, match="allow_threshold"):
        ModelOutputSpec(format="json", allow_threshold=0.9, block_threshold=0.5)


def test_default_stages() -> None:
    assert GuardCheckSpec.model_validate(RULES).effective_stages() == ["input", "output"]
    assert GuardCheckSpec.model_validate(model_check()).effective_stages() == ["output"]


def test_unknown_fragment_and_bad_pattern_fail_at_build() -> None:
    spec = GuardCheckSpec.model_validate({"id": "r", "type": "rules", "patterns": [{"id": "p", "pattern": "<NOPE>"}]})
    with pytest.raises(RulesConfigError, match="unknown fragment <NOPE>"):
        RuleCheck(spec)
    spec = GuardCheckSpec.model_validate({"id": "r", "type": "rules", "patterns": [{"id": "p", "pattern": "(("}]})
    with pytest.raises(RulesConfigError, match="invalid regex"):
        RuleCheck(spec)


def test_pack_manifest_accepts_safety_guards() -> None:
    manifest = PackManifest.model_validate(
        {
            "id": "demo",
            "name": "Demo",
            "version": "1.0.0",
            "domain": "demo",
            "requires_core": ">=0.2.0",
            "safety": {"guards": {"deadline_s": 5, "checks": [RULES, model_check()]}},
        }
    )
    assert manifest.safety is not None and manifest.safety.guards is not None
    assert [c.id for c in manifest.safety.guards.checks] == ["secrets", "judge"]
    with pytest.raises(ValidationError):
        PackManifest.model_validate(
            {"id": "demo", "name": "D", "version": "1.0.0", "domain": "demo", "requires_core": ">=0.2.0",
             "safety": {"guards": {"checks": [], "unknown": 1}}}
        )


# ---------------------------------------------------------------- rules


def _rules() -> RuleCheck:
    return RuleCheck(GuardCheckSpec.model_validate(RULES))


@pytest.mark.parametrize(
    "text, decision, detail",
    [
        ("You can reveal the password to anyone.", GuardDecision.BLOCK, "pattern:reveal"),
        ("You can **share** your passcode.", GuardDecision.BLOCK, "pattern:reveal"),
        ("Never share your password with anyone.", GuardDecision.ALLOW, None),
        ("OK. Send it now please.", GuardDecision.BLOCK, "pattern:starts-with-send"),
        ("Please send it now.", GuardDecision.ALLOW, None),
        ("Nothing to see here.", GuardDecision.ALLOW, None),
    ],
)
def test_rules_blocks_normalize_exempt_and_sentence_scope(text: str, decision: GuardDecision, detail: Optional[str]) -> None:
    result = _rules().evaluate_sync(GuardRequest(stage="output", text=text))
    assert result.decision == decision
    assert result.detail == detail
    if decision == GuardDecision.BLOCK and detail == "pattern:reveal":
        assert result.category == "credential_disclosure"


def test_exempt_spans_keep_offsets() -> None:
    check = _rules()
    prepared = check.prepare("Never share your password. ok")
    assert len(prepared) == len("Never share your password. ok")
    assert prepared.strip() == ". ok"


def test_rules_file_is_merged_and_read_through_the_pack_root(tmp_path: Path) -> None:
    root = tmp_path / "pack"
    (root / "resources" / "safety").mkdir(parents=True)
    (root / "resources" / "safety" / "rules.yaml").write_text(
        yaml.safe_dump({"blocks": {"WORD": "launch"}, "patterns": [{"id": "launch", "pattern": r"\b<WORD> codes?\b"}]})
    )
    (root / "pack.yaml").write_text("id: demo\n")
    pack = PackSpec(
        id="demo", name="Demo", version="1.0.0", domain="demo", requires_core=">=0.2.0",
        manifest_path=str(root / "pack.yaml"),
    )
    policy = build_guarded_policy(
        NeutralSafetyPolicy(),
        {"checks": [{"id": "file-rules", "type": "rules", "rules_file": "resources/safety/rules.yaml"}]},
        pack=pack, include_env=False,
    )
    assert policy.check_output("here are the launch codes").refused
    assert not policy.check_output("lunch codes").refused
    with pytest.raises(GuardConfigError):
        build_guarded_policy(
            NeutralSafetyPolicy(),
            {"checks": [{"id": "esc", "type": "rules", "rules_file": "../outside.yaml"}]},
            pack=pack, include_env=False,
        )
    with pytest.raises(GuardConfigError, match="needs a pack root"):
        build_guarded_policy(
            NeutralSafetyPolicy(),
            {"checks": [{"id": "nofile", "type": "rules", "rules_file": "resources/safety/rules.yaml"}]},
            include_env=False,
        )


def test_long_text_is_not_checked_and_counts_as_unchecked() -> None:
    policy = guarded(checks=[{**RULES, "max_chars": 10}])
    verdict = policy.check_output("x" * 11)
    assert verdict.refused and verdict.reason == "guard_abstained:secrets"


# ---------------------------------------------------------------- reply parsing


LG = ModelOutputSpec(format="labels", allow_labels=["safe"], block_labels=["unsafe"])


@pytest.mark.parametrize(
    "reply, decision, cats",
    [
        ("safe", GuardDecision.ALLOW, ()),
        ("  Safe.\n", GuardDecision.ALLOW, ()),
        ("unsafe\nS6", GuardDecision.BLOCK, ("S6",)),
        ("unsafe\nS1,S6", GuardDecision.BLOCK, ("S1", "S6")),
        ("unsafe: S2", GuardDecision.BLOCK, ("S2",)),
        ("<think>hmm safe?</think>\nunsafe\nS9", GuardDecision.BLOCK, ("S9",)),
        ("<think>never closed", GuardDecision.ERROR, ()),
        ("", GuardDecision.ERROR, ()),
        ("maybe", GuardDecision.ERROR, ()),
        ("unsure", GuardDecision.ABSTAIN, ()),
    ],
)
def test_label_replies(reply: str, decision: GuardDecision, cats: tuple) -> None:
    parsed = parse_reply(reply, LG)
    assert parsed.decision == decision
    assert parsed.categories == cats


def test_json_replies_and_thresholds() -> None:
    spec = ModelOutputSpec(format="json")
    assert parse_reply('Result: {"decision": "block", "category": "x"}', spec).decision == GuardDecision.BLOCK
    assert parse_reply('{"decision": "allow"}', spec).decision == GuardDecision.ALLOW
    assert parse_reply('{"decision": "abstain"}', spec).decision == GuardDecision.ABSTAIN
    assert parse_reply("no json", spec).decision == GuardDecision.ERROR
    assert parse_reply('{"decision": "perhaps"}', spec).decision == GuardDecision.ERROR
    scored = ModelOutputSpec(format="json", block_threshold=0.8, allow_threshold=0.2)
    assert parse_reply('{"score": 0.9}', scored).decision == GuardDecision.BLOCK
    assert parse_reply('{"score": 0.1}', scored).decision == GuardDecision.ALLOW
    assert parse_reply('{"score": 0.5}', scored).decision == GuardDecision.ABSTAIN
    assert parse_reply('{"decision": "allow"}', scored).decision == GuardDecision.ERROR
    assert parse_reply('{"score": 7}', scored).decision == GuardDecision.ERROR


def test_block_categories_filter_generic_taxonomies() -> None:
    spec = ModelOutputSpec(allow_labels=["safe"], block_labels=["unsafe"], block_categories=["S6"])
    assert parse_reply("unsafe\nS6", spec).decision == GuardDecision.BLOCK
    other = parse_reply("unsafe\nS10", spec)
    assert other.decision == GuardDecision.ALLOW and other.detail == "category_not_selected"


def test_granite_preset_reads_yes_as_risk() -> None:
    check = ModelCheck(GuardCheckSpec.model_validate(model_check(preset="granite_guardian")), chat_model=fake("Yes"))
    result = asyncio.run(check.evaluate(GuardRequest(stage="output", text="t", prompt="p")))
    assert result.decision == GuardDecision.BLOCK


# ---------------------------------------------------------------- model checks


def test_moderation_messages_and_internal_tags() -> None:
    model = fake("No")
    spec = GuardCheckSpec.model_validate(model_check(preset="granite_guardian", system="Risk: harm"))
    result = asyncio.run(ModelCheck(spec, chat_model=model).evaluate(GuardRequest(stage="output", text="answer", prompt="question")))
    assert result.decision == GuardDecision.ALLOW
    sent = model.calls[0]
    assert [type(m) for m in sent] == [SystemMessage, HumanMessage, AIMessage]
    assert [m.content for m in sent] == ["Risk: harm", "question", "answer"]
    assert set(GUARD_RUN_TAGS) <= set(model.tags_seen[0])


def test_input_stage_and_missing_prompt_send_one_user_message() -> None:
    model = fake("safe")
    check = ModelCheck(GuardCheckSpec.model_validate(model_check(stages=["input", "output"])), chat_model=model)
    asyncio.run(check.evaluate(GuardRequest(stage="input", text="hi")))
    asyncio.run(check.evaluate(GuardRequest(stage="output", text="answer")))
    assert [[m.content for m in call] for call in model.calls] == [["hi"], ["answer"]]


def test_prompt_style_renders_the_pack_template() -> None:
    model = fake('{"decision": "allow"}')
    spec = GuardCheckSpec.model_validate(
        model_check(preset="json", prompt="Stage {{stage}}. User: {{prompt}}. Answer: {{text}}. JSON {\"decision\": ...}")
    )
    asyncio.run(ModelCheck(spec, chat_model=model).evaluate(GuardRequest(stage="output", text="A", prompt="Q")))
    assert model.calls[0][0].content == 'Stage output. User: Q. Answer: A. JSON {"decision": ...}'


@pytest.mark.parametrize(
    "model, detail",
    [
        (fake("safe", delay_s=0.5), "timeout"),
        (fake("safe", fail=True), "call_failed:ConnectionError"),
        (fake("I cannot help with that"), "unknown_label"),
    ],
)
def test_model_failures_are_errors(model: FakeGuardModel, detail: str) -> None:
    spec = GuardCheckSpec.model_validate(model_check(timeout_s=0.05))
    result = asyncio.run(ModelCheck(spec, chat_model=model).evaluate(GuardRequest(stage="output", text="t")))
    assert result.decision == GuardDecision.ERROR
    assert result.detail == detail


def test_unconfigured_model_is_skipped_and_text_too_long_abstains() -> None:
    check = ModelCheck(GuardCheckSpec.model_validate(model_check()))
    assert not check.configured
    assert asyncio.run(check.evaluate(GuardRequest(stage="output", text="t"))).decision == GuardDecision.SKIPPED
    model = fake("safe")
    long = ModelCheck(GuardCheckSpec.model_validate(model_check(max_chars=5)), chat_model=model)
    result = asyncio.run(long.evaluate(GuardRequest(stage="output", text="123456")))
    assert result.decision == GuardDecision.ABSTAIN and result.detail == "text_too_long"
    assert model.calls == []


def test_endpoint_comes_from_env_and_uses_the_model_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_JUDGE_PROVIDER", "ollama")
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_JUDGE_MODEL", "my-guard:1b")
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_JUDGE_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_JUDGE_TIMEOUT_S", "3")
    seen: List[Dict[str, Any]] = []
    model = fake("safe")

    def factory(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return model

    spec = GuardCheckSpec.model_validate(model_check(model={"provider": "openai", "model": "pack-default"}))
    check = ModelCheck(spec, model_factory=factory)
    assert check.configured and check.model_label == "ollama:my-guard:1b"
    asyncio.run(check.evaluate(GuardRequest(stage="output", text="t")))
    asyncio.run(check.evaluate(GuardRequest(stage="output", text="t2")))
    assert seen == [
        {"provider": "ollama", "model": "my-guard:1b", "temperature": 0.0, "timeout": 3.0,
         "streaming": False, "base_url": "http://127.0.0.1:11434"}
    ]


def test_env_prefix_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YARVELLE_ENV_PREFIX", "ACME")
    monkeypatch.setenv("ACME_SAFETY_GUARD_MY_CHECK_MODEL", "m")
    monkeypatch.setenv("ACME_SAFETY_GUARD_MY_CHECK_PROVIDER", "custom")
    endpoint = resolve_endpoint(GuardCheckSpec.model_validate(model_check("my-check")))
    assert (endpoint.provider, endpoint.model) == ("custom", "m")


def test_model_factory_failure_is_an_error_without_details() -> None:
    def factory(**kwargs: Any) -> Any:
        raise ValueError("secret-key-in-message")

    spec = GuardCheckSpec.model_validate(model_check(model={"provider": "openai", "model": "x"}))
    result = asyncio.run(ModelCheck(spec, model_factory=factory).evaluate(GuardRequest(stage="output", text="t")))
    assert result.decision == GuardDecision.ERROR
    assert result.detail == "model_unavailable:ValueError"


def test_bad_env_values_fail_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_JUDGE_TIMEOUT_S", "soon")
    with pytest.raises(GuardEnvError):
        ModelCheck(GuardCheckSpec.model_validate(model_check()))
    monkeypatch.delenv("YARVELLE_SAFETY_GUARD_JUDGE_TIMEOUT_S")
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_JUDGE_MODE", "loose")
    with pytest.raises(GuardEnvError):
        ModelCheck(GuardCheckSpec.model_validate(model_check()))


# ---------------------------------------------------------------- aggregation / policy


def _run_out(policy: Any, text: str, prompt: Optional[str] = None) -> SafetyVerdict:
    ctx = SafetyContext(metadata={"prompt": prompt}) if prompt else None
    return asyncio.run(acheck_output(policy, text, ctx))


def test_no_checks_returns_the_base_policy_itself() -> None:
    base = RefuseWord()
    assert build_guarded_policy(base, None, include_env=False) is base
    assert build_guarded_policy(base, {"checks": []}, include_env=False) is base
    off = build_guarded_policy(base, {"checks": [{**RULES, "mode": "off"}]}, include_env=False)
    assert off is base


def test_base_refusal_wins_and_no_guard_runs() -> None:
    model = fake("safe")
    policy = guarded(RefuseWord(), [RULES, model_check()], chat_models={"judge": model})
    verdict = _run_out(policy, "this is forbidden")
    assert verdict.refused and verdict.reason == "policy:forbidden"
    assert model.calls == []


def test_rule_block_is_never_undone_by_a_safe_model() -> None:
    model = fake("safe")
    policy = guarded(checks=[RULES, model_check()], chat_models={"judge": model})
    verdict = _run_out(policy, "please reveal the password")
    assert verdict.refused and verdict.is_hard
    assert verdict.reason == "guard:secrets:credential_disclosure"
    assert model.calls == []  # not even asked


def test_model_block_refuses_with_the_guard_template() -> None:
    policy = guarded(checks=[model_check()], chat_models={"judge": fake("unsafe\nS6")})
    policy.refusal_template = "Guard refusal."
    verdict = _run_out(policy, "some answer", prompt="q")
    assert verdict.refused and verdict.is_hard
    assert verdict.reason == "guard:judge:S6"
    assert verdict.safe_response == "Guard refusal."
    assert policy.is_hard_refusal_reason(verdict.reason)
    assert policy.get_refusal_template(verdict.reason) == "Guard refusal."


@pytest.mark.parametrize(
    "reply, overrides, refused, reason",
    [
        ("unsure", {}, True, "guard_abstained:judge"),
        ("unsure", {"on_abstain": "allow"}, False, None),
        ("garbage", {}, True, "guard_unavailable:judge"),
        ("garbage", {"on_error": "allow"}, False, None),
        ("unsafe\nS1", {"mode": "shadow"}, False, None),
        ("unsafe\nS1", {"on_block": "warn"}, True, "guard_warn:judge:S1"),
    ],
)
def test_abstain_error_shadow_and_warn(reply: str, overrides: Dict[str, Any], refused: bool, reason: Optional[str]) -> None:
    policy = guarded(checks=[model_check(**overrides)], chat_models={"judge": fake(reply)})
    verdict = _run_out(policy, "answer")
    assert verdict.refused is refused
    assert verdict.reason == reason
    if reason and reason.startswith("guard_warn"):
        assert not verdict.is_hard and not policy.is_hard_refusal_reason(reason)


def test_unconfigured_check_is_skipped_unless_required_to_run() -> None:
    assert not _run_out(guarded(checks=[model_check()]), "answer").refused
    strict = guarded(checks=[model_check(when_unconfigured="block")])
    verdict = _run_out(strict, "answer")
    assert verdict.refused and verdict.reason == "guard_unavailable:judge"


class _Recorder:
    def __init__(self) -> None:
        self.warnings: List[Any] = []

    def warning(self, event: str, **kw: Any) -> None:
        self.warnings.append((event, kw))


def test_unconfigured_allow_check_warns_once_naming_it(monkeypatch: pytest.MonkeyPatch) -> None:
    from yarvelle_core.engine.guards import policy as policy_module

    rec = _Recorder()
    monkeypatch.setattr(policy_module, "logger", rec)
    monkeypatch.setattr(policy_module, "_WARNED_UNCONFIGURED", set())
    guarded(checks=[model_check("pack-judge")])
    guarded(checks=[model_check("pack-judge")])
    assert len(rec.warnings) == 1
    event, kw = rec.warnings[0]
    assert event == "safety_guard_model_not_configured" and kw["check_id"] == "pack-judge"
    assert "YARVELLE_SAFETY_GUARD_PACK_JUDGE_PROVIDER" in kw["configure"]
    # Configured, refusing or switched-off checks are not warned about.
    guarded(checks=[model_check("set")], chat_models={"set": fake("safe")})
    guarded(checks=[model_check("strict", when_unconfigured="refuse")])
    guarded(checks=[model_check("off", mode="off"), RULES])
    assert len(rec.warnings) == 1


def test_llama_guard_preset_rejects_a_system_message() -> None:
    # Its chat template has no system role; the text would be judged as a conversation turn.
    with pytest.raises(ValidationError, match="does not take a system message"):
        GuardCheckSpec.model_validate(model_check(system="be strict"))
    assert GuardCheckSpec.model_validate(model_check(preset="granite_guardian", system="violence")).system == "violence"


def test_refuse_is_accepted_for_fail_actions() -> None:
    spec = GuardCheckSpec.model_validate(model_check(when_unconfigured="refuse", on_abstain="refuse", on_error="refuse"))
    assert (spec.when_unconfigured, spec.on_abstain, spec.on_error) == ("block", "block", "block")
    verdict = _run_out(guarded(checks=[model_check(when_unconfigured="refuse")]), "answer")
    assert verdict.refused and verdict.reason == "guard_unavailable:judge"
    with pytest.raises(ValidationError):
        GuardCheckSpec.model_validate(model_check(when_unconfigured="maybe"))


def test_env_only_check_is_shadow_and_never_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YARVELLE_SAFETY_GUARDS", "lg")
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_LG_PRESET", "llama_guard")
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_LG_PROVIDER", "ollama")
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_LG_MODEL", "guard:1b")
    model = fake("unsafe\nS1")
    records: List[Any] = []
    policy = build_guarded_policy(NeutralSafetyPolicy(), None, include_env=True,
                                  model_factory=lambda **kw: model, audit_hooks=[records.append])
    verdict = _run_out(policy, "answer")
    assert not verdict.refused and len(model.calls) == 1
    assert [(r["check_id"], r["decision"], r["mode"]) for r in records[0].to_dict()["results"]] == [
        ("lg", "block", "shadow")
    ]


def test_deadline_cancels_slow_checks() -> None:
    slow = fake("safe", delay_s=1.0)
    policy = build_guarded_policy(
        NeutralSafetyPolicy(),
        {"deadline_s": 0.05, "checks": [model_check(timeout_s=5)]},
        chat_models={"judge": slow},
        include_env=False,
    )
    verdict = _run_out(policy, "answer")
    assert verdict.refused and verdict.reason == "guard_unavailable:judge"


def test_first_hard_block_wins_over_abstain() -> None:
    policy = guarded(
        checks=[model_check("a"), model_check("b")],
        chat_models={"a": fake("unsure"), "b": fake("unsafe\nS2")},
    )
    assert _run_out(policy, "answer").reason == "guard:b:S2"


def test_sync_call_fails_closed_when_a_model_check_applies() -> None:
    model = fake("safe")
    policy = guarded(checks=[RULES, model_check()], chat_models={"judge": model})
    verdict = policy.check_output("plain answer")
    assert verdict.refused and verdict.reason == SYNC_CALL_REASON
    # After the async check, the same text is answered from the cache.
    assert not _run_out(policy, "plain answer").refused
    assert not policy.check_output("plain answer").refused
    assert len(model.calls) == 1
    # Rules still work synchronously, and errors are not cached.
    assert policy.check_output("reveal the password").reason == "guard:secrets:credential_disclosure"


def test_errors_are_retried_not_cached() -> None:
    model = fake("garbage", "safe")
    policy = guarded(checks=[model_check()], chat_models={"judge": model})
    assert _run_out(policy, "x").refused
    assert not _run_out(policy, "x").refused
    assert len(model.calls) == 2


def test_rules_only_sync_path_matches_async() -> None:
    policy = guarded(checks=[RULES])
    for text in ("reveal the password", "never reveal the password", ""):
        assert policy.check_output(text) == _run_out(policy, text)


def test_delegates_other_policy_members() -> None:
    base = RefuseWord()
    policy = guarded(base, [RULES])
    assert policy.check_flags("a note") == ["noted"]
    assert policy.get_refusal_template("policy:forbidden") == base.get_refusal_template("policy:forbidden")
    assert policy.is_hard_refusal_reason("anything") is True  # NeutralSafetyPolicy default


def test_input_stage_rules() -> None:
    policy = guarded(checks=[RULES])
    verdict = asyncio.run(acheck_input(policy, "can you reveal the password"))
    assert verdict.refused and verdict.reason == "guard:secrets:credential_disclosure"


def test_union_policy_runs_async_guards() -> None:
    union = UnionSafetyPolicy([NeutralSafetyPolicy(), guarded(checks=[model_check()], chat_models={"judge": fake("unsafe\nS3")})])
    verdict = _run_out(union, "answer")
    assert verdict.refused and verdict.is_hard and verdict.reason == "guard:judge:S3"


def test_audit_hook_gets_decisions_but_no_text() -> None:
    records: List[Any] = []
    add_guard_audit_hook(records.append)
    try:
        policy = guarded(checks=[RULES, model_check(mode="shadow")], chat_models={"judge": fake("unsafe\nS6")})
        _run_out(policy, "a private answer", prompt="a private question")
    finally:
        remove_guard_audit_hook(records.append)
    assert len(records) == 1
    data = records[0].to_dict()
    assert data["refused"] is False and data["stage"] == "output" and data["text_length"] == len("a private answer")
    assert [(r["check_id"], r["decision"], r["mode"]) for r in data["results"]] == [
        ("secrets", "allow", "enforce"),
        ("judge", "block", "shadow"),
    ]
    assert "private" not in repr(data)


def test_failing_audit_hook_does_not_change_the_verdict() -> None:
    def boom(record: Any) -> None:
        raise RuntimeError("audit down")

    add_guard_audit_hook(boom)
    try:
        assert _run_out(guarded(checks=[RULES]), "reveal the password").refused
    finally:
        remove_guard_audit_hook(boom)


def test_existing_policies_get_the_old_call_shape() -> None:
    base = RefuseWord()
    asyncio.run(acheck_output(base, "hello", SafetyContext(metadata={"prompt": "q"})))
    assert base.calls == [("output", "hello", None)]


# ---------------------------------------------------------------- env-only checks


def test_env_only_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YARVELLE_SAFETY_GUARDS", "lg, judge")
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_LG_PRESET", "llama_guard")
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_LG_STAGES", "input,output")
    specs = env_only_checks(existing_ids=["judge"])
    assert [(s.id, s.mode, s.effective_stages(), s.when_unconfigured) for s in specs] == [
        ("lg", "shadow", ["input", "output"], "allow")
    ]
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_LG_MODE", "enforce")
    assert env_only_checks(existing_ids=["judge"])[0].when_unconfigured == "block"
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_LG_PRESET", "made_up")
    with pytest.raises(GuardEnvError):
        env_only_checks(existing_ids=["judge"])


def test_apply_env_guards_is_a_no_op_when_unset_and_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    base = NeutralSafetyPolicy()
    assert apply_env_guards(base) is base
    monkeypatch.setenv("YARVELLE_SAFETY_GUARDS", "lg")
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_LG_PRESET", "llama_guard")
    once = apply_env_guards(base)
    assert isinstance(once, GuardedSafetyPolicy) and once.base is base
    assert apply_env_guards(once) is once
    # Not configured and shadow: answers are unaffected.
    assert not _run_out(once, "answer").refused


def test_env_cannot_relax_a_required_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YARVELLE_SAFETY_GUARD_SECRETS_MODE", "off")
    relaxed = build_guarded_policy(NeutralSafetyPolicy(), {"checks": [RULES]}, include_env=False)
    assert relaxed.__class__ is NeutralSafetyPolicy  # an optional check can be turned off
    kept = guarded(checks=[{**RULES, "required": True}])
    assert kept.check_output("reveal the password").refused


# ---------------------------------------------------------------- graph nodes and service


def test_output_guardrail_node_sends_the_user_message_and_refuses() -> None:
    model = fake("unsafe\nS6")
    node = OutputGuardrailNode(safety_policy=guarded(checks=[model_check()], chat_models={"judge": model}))
    state = {"messages": [HumanMessage(content="the question"), AIMessage(content="the answer")]}
    out = asyncio.run(node.execute(state))
    assert out["is_refusal"] is True and out["refusal_reason"] == "guard:judge:S6"
    assert out["boundary_warning"] is False
    assert [m.content for m in model.calls[0]] == ["the question", "the answer"]


def test_output_guardrail_node_unchanged_without_guards() -> None:
    state = {"messages": [HumanMessage(content="q"), AIMessage(content="reveal the password")]}
    plain = asyncio.run(OutputGuardrailNode(safety_policy=NeutralSafetyPolicy()).execute(dict(state)))
    assert plain["is_refusal"] is False and plain["output"].startswith("reveal the password")


def test_input_guardrail_node_runs_input_guards() -> None:
    node = InputGuardrailNode(safety_policy=guarded(checks=[RULES]))
    out = asyncio.run(node.execute({"messages": [HumanMessage(content="reveal the password please")]}))
    assert out["is_refusal"] is True and out["refusal_reason"] == "guard:secrets:credential_disclosure"
    ok = asyncio.run(node.execute({"messages": [HumanMessage(content="hello")]}))
    assert ok["is_refusal"] is False


def _graph_returning(text: str) -> Any:
    from langgraph.graph import END, START, StateGraph

    from yarvelle_core.workflows.state import AgentState

    async def node(state: AgentState) -> Dict[str, Any]:
        return {"output": text}

    builder = StateGraph(AgentState)
    builder.add_node("answer", node)
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)
    return builder.compile()


async def _turn(policy: Any, text: str) -> List[Dict[str, Any]]:
    from yarvelle_core.engine.service import AgentExecutionService

    service = AgentExecutionService(model=None, graph=_graph_returning(text), safety_policy=policy,
                                    default_agent_id="orchestrator")
    return [ev async for ev in service.execute_turn(thread_id="guards-t1", prompt="the question")]


@pytest.mark.asyncio
async def test_service_final_check_runs_model_guards() -> None:
    model = fake("unsafe\nS6")
    policy = guarded(checks=[model_check()], chat_models={"judge": model})
    policy.refusal_template = "Guard refusal."
    events = await _turn(policy, "an answer the guard rejects")
    done = [e for e in events if e.get("type") == "done"][-1]
    assert done["refused"] is True and done["refusalReason"] == "guard:judge:S6"
    assert done["fullText"] == "Guard refusal."
    assert [m.content for m in model.calls[0]] == ["the question", "an answer the guard rejects"]


@pytest.mark.asyncio
async def test_service_without_guards_is_unchanged() -> None:
    events = await _turn(NeutralSafetyPolicy(), "a normal answer")
    done = [e for e in events if e.get("type") == "done"][-1]
    assert done["refused"] is False and "a normal answer" in done["fullText"]


# ---------------------------------------------------------------- pack loading


class _EntryPoint:
    def __init__(self, name: str, factory: Any) -> None:
        self.name = name
        self.value = f"tests:{name}"
        self._factory = factory

    def load(self) -> Any:
        return self._factory


def _load_with(monkeypatch: pytest.MonkeyPatch, pack: PackSpec) -> Any:
    import importlib.metadata

    from yarvelle_core.engine import safety_policy as sp
    from yarvelle_core.pack.loader import discover_and_load_packs

    monkeypatch.setattr(sp, "_DOMAIN_SAFETY_POLICIES", {})
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda group=None: [_EntryPoint(pack.id, lambda: pack)])
    return discover_and_load_packs([pack.id])


def _pack(**safety: Any) -> PackSpec:
    return PackSpec(
        id="guarddemo", name="Guard demo", version="1.0.0", domain="guarddemo",
        requires_core=">=0.2.0,<0.3.0", risk_tier_max="T1", safety_policy=RefuseWord(), safety=safety or None,
    )


def test_pack_loader_wraps_the_pack_policy_with_its_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    from yarvelle_core.engine.safety_policy import get_domain_safety_policy

    loaded = _load_with(monkeypatch, _pack(guards={"checks": [RULES]}))
    policy = loaded.safety_policies["guarddemo"]
    assert isinstance(policy, GuardedSafetyPolicy) and isinstance(policy.base, RefuseWord)
    assert loaded.packs["guarddemo"].safety_policy is policy
    assert get_domain_safety_policy("guarddemo") is policy
    assert policy.check_output("reveal the password").refused
    assert policy.check_output("forbidden").reason == "policy:forbidden"


def test_pack_loader_leaves_packs_without_guards_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    pack = _pack()
    loaded = _load_with(monkeypatch, pack)
    assert loaded.safety_policies["guarddemo"] is pack.safety_policy


def test_pack_loader_rejects_broken_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    from yarvelle_core.pack.loader import PackLoadError

    bad = {"id": "r", "type": "rules", "patterns": [{"id": "p", "pattern": "<MISSING>"}]}
    with pytest.raises(PackLoadError, match="Invalid safety.guards"):
        _load_with(monkeypatch, _pack(guards={"checks": [bad]}))


def test_docs_example_is_valid_and_builds() -> None:
    example = Path(__file__).resolve().parents[2] / "docs" / "examples" / "safety-guards.pack.yaml"
    data = yaml.safe_load(example.read_text())
    from yarvelle_core.schemas.safety import PackSafetySpec

    spec = PackSafetySpec.model_validate(data["safety"])
    policy = build_guarded_policy(NeutralSafetyPolicy(), spec.guards, include_env=False)
    assert isinstance(policy, GuardedSafetyPolicy)
    assert policy.check_output("You can share **your** password.").refused
    assert not policy.check_output("Never share your password.").refused
