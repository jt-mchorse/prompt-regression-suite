"""Render `DiffResult`s as a self-contained HTML report (#3).

Inputs:
- A list of `(snapshot_id, DiffResult, candidate_text)` tuples — one entry
  per snapshot evaluated in a run.

Outputs:
- A single HTML string with embedded CSS. No JS, no external assets. Each
  snapshot section gets an HTML anchor (`#snapshot-<id>`) so a CI artifact
  URL can deep-link to a specific failure.

Verdict color coding mirrors the diff layer's vocabulary: `pass` (green),
`warn` (amber), `fail` (red). The fail and warn sections render the
semantic-category scores + slot deltas tables; the pass sections collapse
to a one-line summary so the report stays scannable.

The report is the artifact CI uploads after the snapshot suite runs;
operators clicking through it should see at-a-glance which snapshots
failed and why.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from prompt_regression.diff import DiffResult


@dataclass(frozen=True)
class ReportEntry:
    """One row in the HTML report: a snapshot id, its diff outcome, and
    the candidate text that was compared. `baseline_text` is the
    snapshot's canonical text, included so the report can render the
    two side-by-side without forcing the consumer to load the snapshot
    YAML separately.
    """

    snapshot_id: str
    diff: DiffResult
    candidate_text: str
    baseline_text: str = ""


@dataclass(frozen=True)
class ErrorEntry:
    """A snapshot that errored before a `DiffResult` could be produced —
    e.g. an embedder/snapshot model mismatch (D-006), a stored-vs-runtime
    embedding dimension mismatch, or a non-finite embedding. These have no
    cosine/threshold/category data, so they get their own entry type rather
    than a synthetic `DiffResult` that would fabricate numbers.

    The `run` CLI counts these in `failed` and exits non-zero; surfacing them
    here keeps the HTML artifact honest — the report CI uploads must not show
    "all pass" while the run actually failed (#71).
    """

    snapshot_id: str
    message: str


# A report row is either a successfully-diffed entry or an errored one.
Entry = ReportEntry | ErrorEntry


def render_report(entries: list[Entry], *, title: str = "Prompt regression report") -> str:
    """Render the full HTML page. Single self-contained string."""
    summary = _summarize(entries)
    sections = [_render_entry(e) for e in entries]
    return _wrap_page(title, summary, sections)


def _summarize(entries: list[Entry]) -> dict[str, int]:
    counts = {"pass": 0, "warn": 0, "fail": 0, "error": 0}
    for e in entries:
        verdict = "error" if isinstance(e, ErrorEntry) else e.diff.verdict
        counts[verdict] = counts.get(verdict, 0) + 1
    counts["total"] = len(entries)
    return counts


def _render_entry(entry: Entry) -> str:
    if isinstance(entry, ErrorEntry):
        return _render_error_entry(entry)
    verdict = entry.diff.verdict
    klass = f"section {verdict}"
    snap_id = html.escape(entry.snapshot_id)
    anchor = f"snapshot-{_safe_anchor(snap_id)}"
    score = f"{entry.diff.cosine_score:.3f}"
    threshold = f"{entry.diff.threshold:.3f}"
    badge = f'<span class="badge {verdict}">{verdict.upper()}</span>'

    parts: list[str] = [
        f'<section class="{klass}" id="{anchor}">',
        f'  <h2>{badge} <a href="#{anchor}" class="anchor">{snap_id}</a></h2>',
        '  <div class="meta">',
        f"    cosine <code>{score}</code> · threshold <code>{threshold}</code>",
        f"    · embedder <code>{html.escape(entry.diff.embedder_model)}</code>",
        f"    vs snapshot-embed <code>{html.escape(entry.diff.snapshot_embedding_model)}</code>",
        "  </div>",
    ]

    if entry.diff.notes:
        parts.append('  <ul class="notes">')
        for note in entry.diff.notes:
            parts.append(f"    <li>{html.escape(note)}</li>")
        parts.append("  </ul>")

    if entry.diff.verdict != "pass":
        parts.append(_render_categories(entry.diff))
        parts.append(_render_slots(entry.diff))
        parts.append(_render_responses(entry))
    else:
        # Pass sections collapse to a one-line note. Operators reading
        # the report want to focus on what failed; passes are noise.
        parts.append('  <p class="passnote">All channels passed; details elided.</p>')

    parts.append("</section>")
    return "\n".join(parts)


def _render_error_entry(entry: ErrorEntry) -> str:
    snap_id = html.escape(entry.snapshot_id)
    anchor = f"snapshot-{_safe_anchor(snap_id)}"
    badge = '<span class="badge error">ERROR</span>'
    return "\n".join(
        [
            f'<section class="section error" id="{anchor}">',
            f'  <h2>{badge} <a href="#{anchor}" class="anchor">{snap_id}</a></h2>',
            '  <ul class="notes">',
            f"    <li>{html.escape(entry.message)}</li>",
            "  </ul>",
            "</section>",
        ]
    )


def _render_categories(diff: DiffResult) -> str:
    if not diff.semantic_category_scores:
        return '  <div class="section-block muted">No semantic categories declared.</div>'
    rows = []
    for cat in diff.semantic_category_scores:
        rows.append(
            f"<tr><td>{html.escape(cat.name)}</td>"
            f'<td class="num">{cat.cosine_to_response:.3f}</td></tr>'
        )
    return (
        '  <div class="section-block">'
        "    <h3>Semantic categories</h3>"
        '    <table class="categories">'
        "      <thead><tr><th>category</th><th>cosine vs response</th></tr></thead>"
        f"      <tbody>{''.join(rows)}</tbody>"
        "    </table>"
        "  </div>"
    )


def _render_slots(diff: DiffResult) -> str:
    if not diff.slot_deltas:
        return '  <div class="section-block muted">No structured slots declared.</div>'
    rows = []
    for slot in diff.slot_deltas:
        klass = "slot-ok" if not slot.is_failure else f"slot-{html.escape(slot.status)}"
        actual = html.escape(repr(slot.actual_value)) if slot.actual_value is not None else "—"
        rows.append(
            f'<tr class="{klass}">'
            f"<td>{html.escape(slot.name)}</td>"
            f"<td><code>{html.escape(slot.expected_type)}</code></td>"
            f"<td>{actual}</td>"
            f"<td>{html.escape(slot.status)}</td>"
            "</tr>"
        )
    return (
        '  <div class="section-block">'
        "    <h3>Structured slots</h3>"
        '    <table class="slots">'
        "      <thead><tr><th>slot</th><th>expected type</th><th>actual</th><th>status</th></tr></thead>"
        f"      <tbody>{''.join(rows)}</tbody>"
        "    </table>"
        "  </div>"
    )


def _render_responses(entry: ReportEntry) -> str:
    return (
        '  <div class="section-block">'
        "    <h3>Responses (baseline vs candidate)</h3>"
        '    <div class="responses">'
        f'      <pre class="response baseline">{html.escape(entry.baseline_text)}</pre>'
        f'      <pre class="response candidate">{html.escape(entry.candidate_text)}</pre>'
        "    </div>"
        "  </div>"
    )


def _safe_anchor(s: str) -> str:
    # GitHub-style anchors: lowercase, only letters/digits/hyphens.
    out = []
    for c in s.lower():
        if c.isalnum():
            out.append(c)
        elif c in " _-":
            out.append("-")
    return "".join(out) or "snapshot"


_CSS = """
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0;
  background: #0b0d12; color: #e8edf2;
  font: 14px/1.5 ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
}
main { max-width: 980px; margin: 32px auto; padding: 0 20px; }
h1 { font-size: 20px; font-weight: 600; margin: 0 0 12px; }
h2 { font-size: 16px; font-weight: 600; margin: 16px 0 8px; }
h3 { font-size: 13px; font-weight: 600; margin: 14px 0 6px; color: #8a93a6; }
code { font-family: ui-monospace, "SFMono-Regular", monospace; font-size: 12px; color: #e8edf2; }
.summary {
  display: flex; gap: 16px; padding: 12px 16px;
  background: #151922; border: 1px solid #232938; border-radius: 10px;
  margin: 0 0 18px;
}
.summary .stat { font-size: 13px; }
.summary .stat strong { font-size: 18px; display: block; }
.summary .pass strong { color: #6ee7b7; }
.summary .warn strong { color: #fcd34d; }
.summary .fail strong { color: #fca5a5; }
.summary .error strong { color: #fca5a5; }
.summary .total strong { color: #93c5fd; }

.section {
  background: #151922; border: 1px solid #232938; border-radius: 10px;
  padding: 14px 18px; margin: 12px 0;
}
.section.pass  { border-left: 3px solid #6ee7b7; }
.section.warn  { border-left: 3px solid #fcd34d; }
.section.fail  { border-left: 3px solid #fca5a5; }
.section.error { border-left: 3px solid #fca5a5; }
.badge {
  display: inline-block; padding: 1px 8px;
  font-size: 11px; font-weight: 600; letter-spacing: 0.05em;
  border-radius: 4px; margin-right: 8px; vertical-align: 2px;
}
.badge.pass { background: rgba(110,231,183,0.16); color: #6ee7b7; }
.badge.warn { background: rgba(252,211,77,0.16); color: #fcd34d; }
.badge.fail { background: rgba(252,165,165,0.16); color: #fca5a5; }
.badge.error { background: rgba(252,165,165,0.16); color: #fca5a5; }

.anchor { color: inherit; text-decoration: none; }
.anchor:hover { text-decoration: underline; }
.meta, .muted { color: #8a93a6; font-size: 12px; }
.section-block { margin: 12px 0 0; }
.notes { color: #fcd34d; font-size: 12px; margin: 6px 0 0; padding-left: 18px; }
.passnote { color: #8a93a6; font-size: 12px; margin: 6px 0 0; }

table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border-bottom: 1px solid #232938; padding: 6px 10px; text-align: left; }
th { color: #8a93a6; font-weight: 500; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.slots .slot-missing td:nth-child(4),
.slots .slot-type_mismatch td:nth-child(4) { color: #fca5a5; }
.slots .slot-ok td:nth-child(4) { color: #6ee7b7; }
.slots .slot-type_unknown td:nth-child(4) { color: #fcd34d; }

.responses {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
}
.response {
  background: #0e1622; border: 1px solid #1a2842; border-radius: 6px;
  padding: 10px 12px; margin: 0; max-height: 320px; overflow: auto;
  font-family: ui-monospace, "SFMono-Regular", monospace;
  white-space: pre-wrap; word-break: break-word; font-size: 12px;
}
.response.baseline::before { content: "baseline "; color: #93c5fd; }
.response.candidate::before { content: "candidate "; color: #fcd34d; }
"""


def _wrap_page(title: str, summary: dict[str, int], sections: list[str]) -> str:
    # The error stat only appears when there's at least one error row, so a
    # clean run keeps the original four-stat header (#71).
    error_stat = (
        f'\n      <div class="stat error"><strong>{summary["error"]}</strong>error</div>'
        if summary.get("error", 0)
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)}</title>
  <style>{_CSS}</style>
</head>
<body>
  <main>
    <h1>{html.escape(title)}</h1>
    <div class="summary">
      <div class="stat total"><strong>{summary.get("total", 0)}</strong>snapshots</div>
      <div class="stat pass"><strong>{summary.get("pass", 0)}</strong>pass</div>
      <div class="stat warn"><strong>{summary.get("warn", 0)}</strong>warn</div>
      <div class="stat fail"><strong>{summary.get("fail", 0)}</strong>fail</div>{error_stat}
    </div>
{chr(10).join(sections)}
  </main>
</body>
</html>
"""
