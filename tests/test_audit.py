import json
from pathlib import Path

import pytest

from agent_flight_recorder.audit import audit_run, find_secrets, redact
from agent_flight_recorder.cli import main
from agent_flight_recorder.report import render_html
from agent_flight_recorder.trace import Event, Run, TraceError, load_runs

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "examples/policy.json").read_text())


def make_run(*events):
    return Run("r", tuple(Event(run_id="r", step=index, **event) for index, event in enumerate(events, 1)))


def detectors(run, policy=POLICY):
    return {finding.detector for finding in audit_run(run, policy).findings}


def example(run_id):
    return next(run for run in load_runs(ROOT / "examples/traces.jsonl") if run.run_id == run_id)


@pytest.mark.parametrize(
    "run_id, expected",
    [
        ("refund-without-approval", "unconfirmed_action"),
        ("claims-success-after-error", "false_success"),
        ("invented-order-details", "ungrounded_value"),
        ("tool-hallucination-and-loop", "hallucinated_tool"),
        ("tool-hallucination-and-loop", "bad_arguments"),
        ("tool-hallucination-and-loop", "retry_loop"),
        ("tool-hallucination-and-loop", "no_final_answer"),
        ("ignored-user-constraint", "constraint_drift"),
        ("data-exfiltration-attempt", "forbidden_tool"),
        ("data-exfiltration-attempt", "secret_leak"),
        ("data-exfiltration-attempt", "budget"),
    ],
)
def test_example_failures_are_detected(run_id, expected):
    assert expected in detectors(example(run_id))


@pytest.mark.parametrize("run_id", ["refund-happy-path", "honest-failure"])
def test_good_behaviour_has_no_findings(run_id):
    result = audit_run(example(run_id), POLICY)
    assert result.findings == ()
    assert result.score == 100 and result.passed


def test_initial_request_does_not_count_as_confirmation():
    run = make_run(
        {"type": "user", "text": "Yes, refund it."},
        {"type": "tool_call", "name": "issue_refund", "args": {"order_id": "A", "amount": 1}},
    )
    assert "unconfirmed_action" in detectors(run)


def test_later_success_clears_false_success():
    run = make_run(
        {"type": "tool_result", "name": "lookup_order", "error": "timeout"},
        {"type": "tool_result", "name": "lookup_order", "output": {"ok": 1}},
        {"type": "final", "text": "Done."},
    )
    assert "false_success" not in detectors(run)


def test_boolean_is_not_accepted_as_number():
    run = make_run(
        {"type": "tool_call", "name": "issue_refund", "args": {"order_id": "A", "amount": True}},
        {"type": "final", "text": "ok"},
    )
    assert "bad_arguments" in detectors(run)


def test_money_comparison_is_numeric():
    run = make_run(
        {"type": "user", "text": "Total?"},
        {"type": "tool_result", "name": "lookup_order", "output": {"total": 1250}},
        {"type": "final", "text": "It was $1,250.00."},
    )
    assert "ungrounded_value" not in detectors(run)


def test_critical_finding_fails_even_with_passing_score():
    run = make_run({"type": "tool_call", "name": "export_all_customers"}, {"type": "final", "text": "ok"})
    result = audit_run(run, POLICY, pass_score=10)
    assert result.score == 60 and not result.passed


def test_card_detection_uses_luhn():
    assert find_secrets("card 4111 1111 1111 1111")
    assert not find_secrets("reference 1234 5678 9012 3456")


def test_redaction_masks_secret():
    masked = redact("key sk-abcdefghijklmnop123456")
    assert "abcdefghijklmnop" not in masked and "redacted" in masked


def test_report_escapes_html_and_redacts_secrets():
    run = make_run(
        {"type": "user", "text": "<script>alert(1)</script> sk-abcdefghijklmnop123456"},
        {"type": "final", "text": "ok"},
    )
    html = render_html([audit_run(run, POLICY)])
    assert "<script>" not in html and "abcdefghijklmnop" not in html


@pytest.mark.parametrize(
    "line, message",
    [
        ("{bad", "invalid JSON"),
        ('{"run_id":"a","step":1}', "missing required field"),
        ('{"run_id":"a","step":1,"type":"nope"}', "unknown event type"),
        ('{"run_id":"a","step":1,"type":"tool_call"}', "tool 'name'"),
    ],
)
def test_malformed_trace_is_rejected(tmp_path, line, message):
    path = tmp_path / "t.jsonl"
    path.write_text(line)
    with pytest.raises(TraceError, match=message):
        load_runs(path)


def test_duplicate_steps_are_rejected(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text('{"run_id":"a","step":1,"type":"user"}\n{"run_id":"a","step":1,"type":"final"}\n')
    with pytest.raises(TraceError, match="duplicate"):
        load_runs(path)


def test_cli_exit_codes_and_outputs(tmp_path):
    html, data = tmp_path / "r.html", tmp_path / "r.json"
    code = main(["audit", str(ROOT / "examples/traces.jsonl"), "--policy", str(ROOT / "examples/policy.json"), "--html", str(html), "--json", str(data)])
    assert code == 1 and html.exists()
    assert len(json.loads(data.read_text())) == 8


def test_cli_returns_2_for_missing_file(tmp_path):
    assert main(["audit", str(tmp_path / "none.jsonl"), "--policy", str(ROOT / "examples/policy.json")]) == 2
