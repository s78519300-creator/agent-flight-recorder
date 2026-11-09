"""Render audit results as one self-contained HTML file."""

from __future__ import annotations

import json
from collections import Counter
from html import escape

from .audit import SEVERITY_ORDER, RunResult, redact
from .trace import Event

STYLE = """
:root{--bg:#0b1020;--panel:#141b2f;--line:#27314d;--text:#e8ecf7;--muted:#99a5c2;--good:#34d399;--critical:#fb7185;--high:#fb923c;--medium:#facc15;--low:#60a5fa;--accent:#a78bfa}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(1000px 500px at 80% -10%,#312e81 0,transparent 60%),var(--bg);color:var(--text);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1080px;margin:auto;padding:40px 20px 64px}.eyebrow{color:var(--accent);font-weight:700;font-size:13px;letter-spacing:.14em;text-transform:uppercase}
h1{font-size:38px;line-height:1.15;margin:6px 0 8px}.sub{color:var(--muted);margin:0 0 28px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:16px}.card,.bars,details{background:var(--panel);border:1px solid var(--line);border-radius:14px}
.card{padding:18px}.card b{display:block;font-size:32px;line-height:1.1}.card span{color:var(--muted);font-size:13px}.bars{padding:18px;margin-bottom:24px}
.bar{display:grid;grid-template-columns:170px 1fr 34px;gap:10px;align-items:center;margin:7px 0;font-size:13px}.track{height:9px;background:#0b1020;border-radius:9px}.fill{display:block;height:9px;border-radius:9px;background:linear-gradient(90deg,var(--accent),var(--critical))}
details{margin:12px 0;overflow:hidden}summary{display:flex;gap:14px;align-items:center;padding:14px 18px;cursor:pointer;list-style:none}summary::-webkit-details-marker{display:none}
.ring{--c:var(--good);width:48px;height:48px;flex:none;border-radius:50%;display:grid;place-items:center;background:conic-gradient(var(--c) calc(var(--s)*1%),#27314d 0)}.ring i{width:38px;height:38px;border-radius:50%;background:var(--panel);display:grid;place-items:center;font:700 13px ui-monospace,monospace}
.fail{--c:var(--critical)}.run{font-weight:700}.meta{color:var(--muted);font-size:13px}.status{margin-left:auto;font-size:12px;font-weight:800;letter-spacing:.08em}.status.ok{color:var(--good)}.status.bad{color:var(--critical)}
.body{border-top:1px solid var(--line);padding:16px 18px}.f{border-left:3px solid;padding:7px 12px;margin:7px 0;background:#0e1427;border-radius:0 8px 8px 0;font-size:14px}.critical{border-color:var(--critical)}.high{border-color:var(--high)}.medium{border-color:var(--medium)}.low{border-color:var(--low)}
.tag{font:700 11px ui-monospace,monospace;margin-right:7px;text-transform:uppercase}.tl{margin:14px 0 0;padding:0;list-style:none}.tl li{display:grid;grid-template-columns:34px 92px 1fr;gap:8px;padding:6px 0;border-top:1px dashed #222c47;font-size:13px}.tl code{font:12px ui-monospace,monospace;color:#c7d2fe;overflow-wrap:anywhere}.n{color:var(--muted);font-family:ui-monospace,monospace}.t{font-weight:700;color:var(--accent)}.err{color:var(--critical)}
footer{color:var(--muted);font-size:13px;margin-top:24px}@media(max-width:640px){h1{font-size:30px}.tl li{grid-template-columns:28px 1fr}.tl code{grid-column:1/-1}.bar{grid-template-columns:120px 1fr 28px}}
"""


def _describe(event: Event) -> str:
    if event.type == "tool_call":
        body = f"{event.name}({json.dumps(event.args, default=str)})"
    elif event.type == "tool_result":
        body = f"{event.name} → ERROR: {event.error}" if event.error else f"{event.name} → {json.dumps(event.output, default=str)}"
    else:
        body = event.text
    return escape(redact(body))


def _run_html(result: RunResult) -> str:
    calls = len(result.run.of_type("tool_call"))
    tokens = sum(event.tokens for event in result.run.events)
    findings = "".join(
        f'<div class="f {finding.severity}"><span class="tag">{finding.severity}</span>'
        f"{'step ' + str(finding.step) + ' · ' if finding.step is not None else ''}{escape(finding.message)}</div>"
        for finding in result.findings
    ) or '<div class="meta">No findings. Every detector passed.</div>'
    timeline = "".join(
        f'<li><span class="n">{event.step}</span><span class="t">{event.type}</span>'
        f'<code class="{"err" if event.error else ""}">{_describe(event)}</code></li>'
        for event in result.run.events
    )
    is_open = "" if result.passed else " open"
    label = "PASS" if result.passed else "FAIL"
    ring = "ring" if result.passed else "ring fail"
    status = "ok" if result.passed else "bad"
    return (
        f'<details{is_open}><summary><span class="{ring}" style="--s:{result.score}"><i>{result.score}</i></span>'
        f'<span><span class="run">{escape(result.run.run_id)}</span><br><span class="meta">{calls} tool calls · '
        f'{tokens:,} tokens · {len(result.findings)} findings</span></span><span class="status {status}">{label}</span></summary>'
        f'<div class="body">{findings}<ul class="tl">{timeline}</ul></div></details>'
    )


def render_html(results: list[RunResult], title: str = "Agent Flight Recorder") -> str:
    total = len(results)
    passed = sum(result.passed for result in results)
    average = round(sum(result.score for result in results) / total) if total else 0
    findings = [finding for result in results for finding in result.findings]
    critical = sum(finding.severity == "critical" for finding in findings)
    by_detector = Counter(finding.detector for finding in findings)
    widest = max(by_detector.values(), default=1)
    bars = "".join(
        f'<div class="bar"><span>{escape(name)}</span><span class="track"><span class="fill" style="width:{count / widest * 100:.0f}%"></span></span><b>{count}</b></div>'
        for name, count in by_detector.most_common()
    ) or '<div class="meta">Nothing to report.</div>'
    ordered = sorted(results, key=lambda result: (result.passed, result.score))
    runs = "".join(_run_html(result) for result in ordered)
    return (
        f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title><style>{STYLE}</style><main>"
        f'<div class="eyebrow">Agent audit report</div><h1>{escape(title)}</h1>'
        f'<p class="sub">Every finding links an agent decision to a step in its trace.</p><section class="cards">'
        f'<div class="card"><b>{passed}/{total}</b><span>runs passed</span></div><div class="card"><b>{average}</b><span>average safety score</span></div>'
        f'<div class="card"><b>{critical}</b><span>critical findings</span></div><div class="card"><b>{len(findings)}</b><span>total findings</span></div></section>'
        f'<section class="bars"><b>Failure modes</b>{bars}</section>{runs}'
        f"<footer>Severity scale: {', '.join(SEVERITY_ORDER)}. Detected secrets are redacted in this report.</footer></main></html>"
    )
