import json
import sys

import pytest
from test_agents import FakeWorkspace

from herdr_courier import agents, cli, config, stops

RECORDS = [
    {
        "lane": "amg",
        "state": "closed",
        "stopped": {"by": "boss", "at": "2026-11-25T15:30:00+09:00", "why": "paused"},
    },
    {
        "lane": "boss",
        "state": "closed",
        "stopped": {"by": "owner", "at": "2026-11-25T09:00:00+09:00", "why": "x"},
    },
    {"lane": "docs", "state": "working"},
    "not a record",
]


def script(tmp_path, body: str) -> tuple[str, ...]:
    path = tmp_path / "stops_cmd.py"
    path.write_text(body, encoding="utf-8")
    return (sys.executable, str(path))


def settings(tmp_path, body: str, timeout: float = 10.0) -> config.Stops:
    return config.Stops(command=script(tmp_path, body), timeout=timeout)


def test_no_command_reads_nothing():
    assert stops.read(config.Stops()) == ([], None)


def test_records_with_a_stop_mark_become_stops(tmp_path):
    found, note = stops.read(settings(tmp_path, f"print({json.dumps(json.dumps(RECORDS))})"))
    assert note is None
    assert [s.lane for s in found] == ["amg", "boss"]
    assert found[0].line() == "amg stopped on purpose at 2026-11-25 15:30 by boss: paused"


@pytest.mark.parametrize(
    ("body", "note"),
    [
        (
            "import sys; sys.stderr.write('no workspace'); sys.exit(1)",
            "stops command exited 1: no workspace",
        ),
        ("print('not json')", "stops command did not print JSON"),
        ("print('{}')", "stops command did not print a JSON list"),
        ("import time; time.sleep(5)", "stops command failed"),
    ],
)
def test_a_command_that_fails_leaves_a_note(tmp_path, body, note):
    found, got = stops.read(settings(tmp_path, body, timeout=1.0))
    assert found == []
    assert got.startswith(note)


def test_a_missing_program_leaves_a_note(tmp_path):
    found, note = stops.read(config.Stops(command=(str(tmp_path / "missing.exe"),)))
    assert found == []
    assert note.startswith("stops command failed")


def test_a_lane_that_runs_again_is_not_shown():
    found = [stops.Stop("amg", "boss", "t", "w"), stops.Stop("boss", "owner", "t", "w")]
    assert stops.not_running(found, {"boss"}) == [found[0]]


def test_render_puts_the_stops_under_the_table():
    text = agents.render(
        [], [], width=62, dispatcher="running", stopped=["amg stopped on purpose at x by boss: y"]
    )
    assert text.splitlines()[-1] == "- amg stopped on purpose at x by boss: y"


def write_config(tmp_path, command: tuple[str, ...]) -> None:
    (tmp_path / "config.toml").write_text(
        "[stops]\ncommand = " + json.dumps(list(command)) + "\n", encoding="utf-8"
    )


def test_cli_agents_shows_stopped_lanes_that_run_nowhere(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("COURIER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "CliHerdr", FakeWorkspace)
    write_config(tmp_path, script(tmp_path, f"print({json.dumps(json.dumps(RECORDS))})"))
    assert cli.main(["agents", "--json"]) == 0
    reply = json.loads(capsys.readouterr().out)
    assert reply["stopped"] == [
        {"lane": "amg", "by": "boss", "at": "2026-11-25T15:30:00+09:00", "why": "paused"}
    ]
    assert cli.main(["agents", "--width", "80"]) == 0
    assert "- amg stopped on purpose at 2026-11-25 15:30 by boss: paused" in capsys.readouterr().out


def test_cli_agents_warns_when_the_stops_command_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("COURIER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "CliHerdr", FakeWorkspace)
    write_config(tmp_path, script(tmp_path, "import sys; sys.exit(2)"))
    assert cli.main(["agents", "--json"]) == 0
    reply = json.loads(capsys.readouterr().out)
    assert reply["stopped"] == []
    assert "stops command exited 2: " in reply["warnings"]


def test_stops_command_must_be_a_list_of_strings(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[stops]\ncommand = "tool list"\n', encoding="utf-8")
    with pytest.raises(config.ConfigError, match="stops.command must be a list of strings"):
        config.load(path)
