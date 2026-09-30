"""Shared design tokens/components for relion-origin's and reliontree's
stdlib-http.server GUIs -- one CSS foundation instead of each project
reinventing inline styles, aimed at closing the gap to cryoSPARC's polish
(BAUPLAN.md ##17): a semantic color system, cards instead of raw tables,
badges for status/quality, and dark mode as a first-class default.

Kept as a plain CSS string, embedded inline (no CDN, no build step) --
same constraint as both tools' HPC-login-node/air-gapped requirement.
There are two copies of this file (relion-origin and reliontree each own
their copy, no shared package dependency between two single-author
sibling projects) -- keep them in sync by hand when editing either.
"""

THEME_CSS = """
:root {
  --bg: #f7f8fa;
  --surface: #ffffff;
  --border: #e2e5ea;
  --text: #1a1d23;
  --text-muted: #6b7280;
  --accent: #2563eb;
  --accent-text: #ffffff;
  --accent-bg: #e8f0fe;
  --accent-bg-hover: #d8e6fd;
  --good: #16a34a;
  --good-bg: #dcfce7;
  --warn: #ca8a04;
  --warn-bg: #fef9c3;
  --bad: #dc2626;
  --bad-bg: #fee2e2;
  --neutral-bg: #eef0f3;
  --radius: 10px;
  --shadow: 0 1px 2px rgba(16, 24, 40, 0.06), 0 1px 3px rgba(16, 24, 40, 0.08);
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px; --space-6: 24px;
}

/* Dark mode: opt-in only via data-theme="dark" for now, not auto from
   prefers-color-scheme -- revisit once the light theme is signed off. */
:root[data-theme="dark"] {
  --bg: #0f1115; --surface: #1a1d24; --border: #2a2e37; --text: #e8eaed;
  --text-muted: #9aa1ac; --accent: #5b9dff; --accent-text: #0f1115;
  --accent-bg: #16283f; --accent-bg-hover: #1c3350;
  --good: #4ade80; --good-bg: #14532d; --warn: #facc15; --warn-bg: #713f12;
  --bad: #f87171; --bad-bg: #7f1d1d; --neutral-bg: #232730;
  --shadow: 0 1px 2px rgba(0, 0, 0, 0.4), 0 2px 6px rgba(0, 0, 0, 0.3);
}

* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  line-height: 1.5;
}
h1, h2, h3 { margin: 0 0 var(--space-2) 0; font-weight: 600; color: var(--text); }
h1 { font-size: 18px; }
h2 { font-size: 14px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; }
a { color: var(--accent); }

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: var(--space-4);
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--space-3);
  margin: var(--space-4) 0;
}
.metric {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--space-3) var(--space-4);
}
.metric .value { font-size: 26px; font-weight: 700; color: var(--text); }
.metric .label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; }

.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.badge-good { background: var(--good-bg); color: var(--good); }
.badge-warn { background: var(--warn-bg); color: var(--warn); }
.badge-bad { background: var(--bad-bg); color: var(--bad); }
.badge-neutral { background: var(--neutral-bg); color: var(--text-muted); }

table { border-collapse: collapse; width: 100%; }
th, td { padding: var(--space-2) var(--space-3); text-align: left; border-bottom: 1px solid var(--border); }
th { font-size: 11px; text-transform: uppercase; letter-spacing: 0.03em; color: var(--text-muted); font-weight: 600; }
tr:last-child td { border-bottom: none; }

button, select, input {
  font: inherit;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 5px 10px;
}
button { cursor: pointer; }
button:hover { background: var(--neutral-bg); }
"""


def badge(label, level="neutral"):
    """A `<span class="badge-...">` for a status/quality label. `level`:
    "good"/"warn"/"bad"/"neutral"."""
    return '<span class="badge badge-%s">%s</span>' % (level, label)


def metric(value, label):
    """A `<div class="metric">` dashboard tile: a large value + small
    label, cryoSPARC-style "state of the project at a glance" summary."""
    return '<div class="metric"><div class="value">%s</div><div class="label">%s</div></div>' % (value, label)
