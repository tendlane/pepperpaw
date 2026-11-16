import json
from pathlib import Path

import pytest

from herdr_courier.core.queue import DISMISS_COOLDOWN, MAX_DISMISS_ATTEMPTS, Dispatcher, State
from herdr_courier.core.transport import HerdrError

AGY_SURVEY = (
    Path(__file__).resolve().parent.parent / "fixtures" / "agy" / "feedback-survey.ansi"
).read_text(encoding="utf-8")


@pytest.mark.parametrize("status", ["idle", "done"])
def test_agy_survey_dismissed_with_escape_only_logged_and_delivered(
    herdr, clock, tmp_path, run, status
):
    logs: list[str] = []
    pane = herdr.add("w1:p1", status=status, custom_screen=AGY_SURVEY)
    d = Dispatcher(herdr, tmp_path / "journal.jsonl", clock=clock, wall=clock, log=logs.append)
    item = d.enqueue("w1:p1", "hello", source="t")

    run(d, 0.0)
    assert pane.escape_calls == 1
    assert pane.submit_calls == 0
    assert pane.enter_calls == 0
    assert pane.submitted == []
    assert any("dismissing CLI experience survey" in line and "Escape" in line for line in logs)

    events = [
        json.loads(line)
        for line in (tmp_path / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        e.get("event") == "dialog_dismissed"
        and e.get("pane_id") == "w1:p1"
        and e.get("id") == item.id
        and e.get("dialog") == "CLI experience survey"
        for e in events
    )

    run(d, 2.0)
    assert item.state in (State.VERIFYING, State.SENT)
    assert pane.submitted == ["hello"]
    assert pane.escape_calls == 1


def test_stuck_agy_survey_respects_cooldown_and_attempt_cap(herdr, make_dispatcher, run):
    pane = herdr.add("w1:p1", custom_screen=AGY_SURVEY, dismiss_on_escape=False)
    d = make_dispatcher()
    item = d.enqueue("w1:p1", "hello", source="t")

    run(d, DISMISS_COOLDOWN * (MAX_DISMISS_ATTEMPTS + 2))
    assert pane.escape_calls == MAX_DISMISS_ATTEMPTS
    assert pane.submit_calls == 0
    assert item.state is State.WAITING
    assert item.reason.startswith("input unknown:")


def test_survey_not_dismissed_while_working_or_held(herdr, make_dispatcher, run):
    pane = herdr.add("w1:p1", status="working", custom_screen=AGY_SURVEY)
    d = make_dispatcher()
    d.enqueue("w1:p1", "hello", source="t")

    run(d, 3.0)
    assert pane.escape_calls == 0

    pane.status = "idle"
    d.hold("w1:p1", owner="console", reason="human active", ttl=10)
    run(d, 3.0)
    assert pane.escape_calls == 0

    d.release("w1:p1")
    run(d, 2.5)
    assert pane.escape_calls == 1
    assert pane.submitted == ["hello"]


def test_trust_dialog_is_never_dismissed(herdr, make_dispatcher, run):
    pane = herdr.add("w1:p1", status="idle", dialog=True)
    d = make_dispatcher()
    item = d.enqueue("w1:p1", "hello", source="t")

    run(d, 10.0)
    assert pane.escape_calls == 0
    assert pane.submit_calls == 0
    assert item.state is State.WAITING
    assert item.reason.startswith("input unknown:")


def test_escape_failure_logs_and_recovers(herdr, clock, tmp_path, run, monkeypatch):
    logs: list[str] = []
    pane = herdr.add("w1:p1", status="idle", custom_screen=AGY_SURVEY)

    def fail_escape(_pane_id: str) -> None:
        pane.escape_calls += 1
        raise HerdrError("cli_timeout", "timed out")

    monkeypatch.setattr(herdr, "escape", fail_escape)
    d = Dispatcher(herdr, tmp_path / "journal.jsonl", clock=clock, wall=clock, log=logs.append)
    item = d.enqueue("w1:p1", "hello", source="t")

    run(d, 0.0)
    assert pane.escape_calls == 1
    assert item.state is State.WAITING
    assert "dialog dismiss failed" in item.reason
    assert any("could not dismiss" in line for line in logs)
