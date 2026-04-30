"""6-step 固定流水线状态机（spec § 3.1）。

约束（不变量）：
- 每个 workflow 任意时刻 ≤ 1 个 running step
- 状态转换必须通过本模块的 transition / validate_transition
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

STEPS: tuple[str, ...] = ("idea", "requirement", "plan", "design", "devtest", "deploy")


class State(StrEnum):
    CREATED = "CREATED"

    IDEA_RUNNING = "IDEA_RUNNING"
    IDEA_DONE = "IDEA_DONE"
    AWAITING_APPROVAL_REQUIREMENT = "AWAITING_APPROVAL_REQUIREMENT"

    REQUIREMENT_RUNNING = "REQUIREMENT_RUNNING"
    REQUIREMENT_DONE = "REQUIREMENT_DONE"
    AWAITING_APPROVAL_PLAN = "AWAITING_APPROVAL_PLAN"

    PLAN_RUNNING = "PLAN_RUNNING"
    PLAN_DONE = "PLAN_DONE"
    AWAITING_APPROVAL_DESIGN = "AWAITING_APPROVAL_DESIGN"

    DESIGN_RUNNING = "DESIGN_RUNNING"
    DESIGN_DONE = "DESIGN_DONE"
    AWAITING_APPROVAL_DEVTEST = "AWAITING_APPROVAL_DEVTEST"

    DEVTEST_RUNNING = "DEVTEST_RUNNING"
    DEVTEST_DONE = "DEVTEST_DONE"
    AWAITING_APPROVAL_DEPLOY = "AWAITING_APPROVAL_DEPLOY"

    DEPLOY_RUNNING = "DEPLOY_RUNNING"
    DEPLOY_DONE = "DEPLOY_DONE"

    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    AWAITING_MANUAL_ACTION = "AWAITING_MANUAL_ACTION"


TERMINAL: frozenset[State] = frozenset({State.COMPLETED, State.ABORTED})


class InvalidTransition(Exception):
    def __init__(self, src: State, dst: State) -> None:
        super().__init__(f"Invalid state transition: {src.value} -> {dst.value}")
        self.src = src
        self.dst = dst


def starting_state() -> State:
    return State.CREATED


def _running_for(step: str) -> State:
    return State[f"{step.upper()}_RUNNING"]


def _done_for(step: str) -> State:
    return State[f"{step.upper()}_DONE"]


def _awaiting_approval_for(step: str) -> State:
    return State[f"AWAITING_APPROVAL_{step.upper()}"]


def next_state_on_success(src: State) -> State:
    """RUNNING → DONE。"""
    if not src.value.endswith("_RUNNING") or src == State.COMPLETED:
        raise InvalidTransition(src, src)
    step = src.value.removesuffix("_RUNNING").lower()
    return _done_for(step)


def next_state_on_failure(src: State) -> State:
    """RUNNING → AWAITING_MANUAL_ACTION。"""
    if not src.value.endswith("_RUNNING"):
        raise InvalidTransition(src, State.AWAITING_MANUAL_ACTION)
    return State.AWAITING_MANUAL_ACTION


def next_running_state(src: State, policy: Mapping[str, str]) -> State:
    """推进到下一 RUNNING（或 AWAITING_APPROVAL / COMPLETED）。

    - CREATED → IDEA_RUNNING
    - <STEP>_DONE:
        - 最后一步 (deploy) → COMPLETED
        - policy[next]='auto' → <NEXT>_RUNNING
        - 否则 → AWAITING_APPROVAL_<NEXT>
    - AWAITING_APPROVAL_<STEP> → <STEP>_RUNNING
    """
    if src == State.CREATED:
        return State.IDEA_RUNNING

    if src.value.endswith("_DONE"):
        step = src.value.removesuffix("_DONE").lower()
        idx = STEPS.index(step)
        if idx == len(STEPS) - 1:
            return State.COMPLETED
        next_step = STEPS[idx + 1]
        if policy.get(next_step, "manual") == "auto":
            return _running_for(next_step)
        return _awaiting_approval_for(next_step)

    if src.value.startswith("AWAITING_APPROVAL_"):
        step = src.value.removeprefix("AWAITING_APPROVAL_").lower()
        return _running_for(step)

    raise InvalidTransition(src, src)


def _build_allowed_transitions() -> set[tuple[State, State]]:
    allowed: set[tuple[State, State]] = set()

    allowed.add((State.CREATED, State.IDEA_RUNNING))

    for i, step in enumerate(STEPS):
        running = _running_for(step)
        done = _done_for(step)
        allowed.add((running, done))
        allowed.add((running, running))
        allowed.add((running, State.AWAITING_MANUAL_ACTION))

        if i < len(STEPS) - 1:
            next_step = STEPS[i + 1]
            next_running = _running_for(next_step)
            awaiting = _awaiting_approval_for(next_step)
            allowed.add((done, next_running))
            allowed.add((done, awaiting))
            allowed.add((awaiting, next_running))
            allowed.add((awaiting, State.ABORTED))
            # UI"重新执行"按钮：用户不接受刚完成的 step 输出，在等待审批下一步时
            # 允许把刚结束的 step 再跑一遍。
            allowed.add((awaiting, running))
        else:
            allowed.add((done, State.COMPLETED))

    for step in STEPS:
        allowed.add((State.AWAITING_MANUAL_ACTION, _running_for(step)))
    allowed.add((State.AWAITING_MANUAL_ACTION, State.ABORTED))
    for i, _step in enumerate(STEPS):
        if i < len(STEPS) - 1:
            next_step = STEPS[i + 1]
            allowed.add((State.AWAITING_MANUAL_ACTION, _running_for(next_step)))
            allowed.add((State.AWAITING_MANUAL_ACTION, _awaiting_approval_for(next_step)))
        else:
            allowed.add((State.AWAITING_MANUAL_ACTION, State.COMPLETED))

    for s in State:
        if s not in TERMINAL:
            allowed.add((s, State.ABORTED))

    return allowed


_ALLOWED: set[tuple[State, State]] = _build_allowed_transitions()


def validate_transition(src: State, dst: State) -> None:
    if src in TERMINAL:
        raise InvalidTransition(src, dst)
    if (src, dst) not in _ALLOWED:
        raise InvalidTransition(src, dst)


def transition(src: State, dst: State) -> State:
    """校验并返回目标状态。调用者负责在 DB 事务里持久化。"""
    validate_transition(src, dst)
    return dst
