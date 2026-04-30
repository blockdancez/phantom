import pytest

from scheduler.engine.state_machine import (
    STEPS,
    InvalidTransition,
    State,
    next_running_state,
    next_state_on_failure,
    next_state_on_success,
    starting_state,
    transition,
    validate_transition,
)


def test_steps_order_matches_spec():
    assert STEPS == ("idea", "requirement", "plan", "design", "devtest", "deploy")


def test_starting_state_is_created():
    assert starting_state() == State.CREATED


def test_created_to_first_running():
    assert next_running_state(State.CREATED, policy={}) == State.IDEA_RUNNING


def test_step_done_auto_goes_to_next_running():
    policy = {"requirement": "auto"}
    nxt = next_running_state(State.IDEA_DONE, policy=policy)
    assert nxt == State.REQUIREMENT_RUNNING


def test_step_done_manual_goes_to_awaiting_approval():
    policy = {"requirement": "manual"}
    nxt = next_running_state(State.IDEA_DONE, policy=policy)
    assert nxt == State.AWAITING_APPROVAL_REQUIREMENT


def test_awaiting_approval_to_next_running():
    nxt = next_running_state(State.AWAITING_APPROVAL_REQUIREMENT, policy={})
    assert nxt == State.REQUIREMENT_RUNNING


def test_last_step_done_goes_to_completed():
    nxt = next_running_state(State.DEPLOY_DONE, policy={})
    assert nxt == State.COMPLETED


def test_success_transition():
    assert next_state_on_success(State.IDEA_RUNNING) == State.IDEA_DONE
    assert next_state_on_success(State.DEPLOY_RUNNING) == State.DEPLOY_DONE


def test_failure_transition():
    assert next_state_on_failure(State.IDEA_RUNNING) == State.AWAITING_MANUAL_ACTION
    assert next_state_on_failure(State.DEVTEST_RUNNING) == State.AWAITING_MANUAL_ACTION


def test_transition_function_accepts_valid():
    transition(State.CREATED, State.IDEA_RUNNING)


def test_transition_function_rejects_invalid():
    with pytest.raises(InvalidTransition):
        transition(State.IDEA_RUNNING, State.DEPLOY_RUNNING)


def test_completed_is_terminal():
    with pytest.raises(InvalidTransition):
        transition(State.COMPLETED, State.IDEA_RUNNING)


def test_aborted_is_terminal():
    with pytest.raises(InvalidTransition):
        transition(State.ABORTED, State.IDEA_RUNNING)


def test_abort_allowed_from_any_non_terminal():
    for s in [
        State.IDEA_RUNNING,
        State.IDEA_DONE,
        State.AWAITING_APPROVAL_REQUIREMENT,
        State.REQUIREMENT_RUNNING,
        State.AWAITING_MANUAL_ACTION,
    ]:
        validate_transition(s, State.ABORTED)


def test_manual_action_recovery_paths():
    validate_transition(State.AWAITING_MANUAL_ACTION, State.IDEA_RUNNING)
    validate_transition(State.AWAITING_MANUAL_ACTION, State.DEVTEST_RUNNING)
    validate_transition(State.AWAITING_MANUAL_ACTION, State.ABORTED)


@pytest.mark.parametrize("step", STEPS)
def test_every_step_has_running_done_states(step):
    running = State[f"{step.upper()}_RUNNING"]
    done = State[f"{step.upper()}_DONE"]
    assert running.value.endswith("_RUNNING")
    assert done.value.endswith("_DONE")
    assert next_state_on_success(running) == done
