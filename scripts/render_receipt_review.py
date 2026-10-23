"""Render the saved receipt experiment into a local, read-only review screen."""

from __future__ import annotations

import html
import json
from pathlib import Path


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def render(review: dict, static: list[dict]) -> str:
    diff = review["evidence"]["E1"]["value"]
    changes = []
    labels = {
        "files_read": "Read an additional file",
        "files_written": "Wrote an additional file",
        "network_hosts": "Contacted an additional destination",
        "processes": "Started an additional program",
        "tools": "Called an additional tool",
    }
    for field, label in labels.items():
        for value in diff["added"][field]:
            changes.append(f"<li><span>{esc(label)}</span><code>{esc(value)}</code></li>")
    static_rows = "".join(
        f"<tr><td>{esc(row['fixture'].title())}</td>"
        f"<td>{esc(row['overall_status'].title())}</td>"
        f"<td>{esc(row['total_warnings'])}</td></tr>"
        for row in static
    )
    refs = esc(", ".join(review["evidence_ids"]))
    raw = esc(json.dumps(review, indent=2))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1">
<title>SkillGuard · Receipt skill review</title>
<style>
:root{{font-family:system-ui,sans-serif;color:#172a30;background:#f4f6f4}}
*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1040px;margin:auto;padding:38px 24px
60px}}
header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:44px}}
.brand{{font-size:21px;font-weight:750}}.tag{{font-size:12px;font-weight:650;padding:8px 12px;
border:1px solid #cbd5d0;border-radius:20px;color:#546960}}h1{{font-size:38px;letter-spacing:-1.2px;
margin:12px 0 14px}}h2{{font-size:19px;margin:0 0
18px}}p{{line-height:1.6}}.lead{{color:#52666b;max-width:690px}}
.eyebrow{{font-size:12px;text-transform:uppercase;letter-spacing:1.8px;color:#647b71;
font-weight:700}}
.grid{{display:grid;grid-template-columns:1.3fr 1fr;gap:22px;margin-top:30px}}
.card{{background:white;border:1px solid #dde4df;border-radius:18px;padding:28px}}
.status{{display:inline-block;background:#fff0d9;color:#775006;border-radius:7px;
padding:7px 10px;font-weight:700;font-size:13px;margin-bottom:18px}}
.task{{border-left:3px solid #95b6a3;padding-left:15px;color:#52666b}}
ul{{list-style:none;margin:0;padding:0}}li{{padding:17px 0;border-top:1px solid #edf1ee}}
li span{{display:block;font-weight:650;font-size:14px}}code{{display:block;color:#91532e;
font-size:12px;overflow-wrap:anywhere;margin-top:9px}}
.callout{{background:#f6f8f5;border-radius:10px;
padding:16px;font-size:13px;color:#52666b;margin-top:22px}}.muted{{color:#65777b;font-size:13px}}
.recommendation{{font-size:26px;font-weight:700;margin:0 0
12px}}table{{width:100%;border-collapse:collapse;
font-size:13px}}th,td{{text-align:left;padding:11px 0;border-bottom:1px solid #edf1ee}}
th{{color:#65777b;font-weight:500}}details{{margin-top:22px}}summary{{cursor:pointer;font-size:13px;
font-weight:650}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:#eef2ee;
padding:16px;border-radius:10px}}footer{{margin-top:26px;font-size:12px;color:#65777b}}
@media(max-width:740px){{.grid{{grid-template-columns:1fr}}h1{{font-size:30px}}
main{{padding:24px 16px}}}}
</style></head><body><main>
<header><div class="brand">SkillGuard</div><span class="tag">Recorded prototype · staged
attack</span></header>
<div class="eyebrow">Review a learned behavior</div><h1>It sorts receipts.<br>It also reaches
beyond them.</h1>
<p class="lead">A new receipt-organizing skill was replayed with fake data inside an OpenShell
sandbox.
Compare its observed behavior with the normal version before trusting it.</p>
<div class="grid"><section class="card"><h2>What changed during replay</h2>
<p class="task">Requested task: organize a receipt locally.</p><ul>{"".join(changes)}</ul>
<div class="callout">Both versions produced the receipt output. The staged version also accessed a
fake private file and sent its contents to a controlled localhost receiver.</div></section>
<section class="card"><span class="status">Activation held</span>
<div class="recommendation">Model advice: {esc(review["model_recommendation"].title())}</div>
<p>{esc(review["explanation"])}</p><p class="muted">Evidence references: {refs}</p>
<div class="callout">The model provides advice. No skill activation or approval was performed.
The current Python audit trace can be evaded by hostile code; independent tracing remains
unresolved.</div>
<p class="muted">{esc(review["model"])}<br>Estimated inference cost:
${review["estimated_cost_usd"]:.6f}</p>
</section><section class="card"><h2>Static checks completed</h2><table>
<thead><tr><th>Fixture</th><th>Tier 1 status</th><th>Warnings</th></tr></thead>
<tbody>{static_rows}</tbody></table><p class="muted">NVIDIA SkillEvaluator, static-only
configuration.
These two fixtures are a demonstration, not a detection benchmark.</p></section>
<section class="card"><h2>Evidence you can inspect</h2><p class="muted">The behavioral diff
comes from
recorded events. The model explanation cites that evidence and cannot add permissions.</p>
<details><summary>View saved review and complete diff</summary><pre>{raw}</pre></details>
</section></div><footer>Local review · fake canary data only · scripts executed directly,
without a model-induced receipt injection or full Hermes agent session.</footer>
</main></body></html>"""


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    review = json.loads((root / "results/receipt_review.json").read_text())
    static = json.loads((root / "results/static/summary.json").read_text())
    output = root.parent / "outputs/receipt-demo"
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(render(review, static))
    (output / "review.json").write_text(json.dumps(review, indent=2) + "\n")
    print(output / "index.html")


if __name__ == "__main__":
    main()
