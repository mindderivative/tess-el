"""What the benchmarks measure: expressions of the kind the Shell and Tesserae UI write.

Each workload is `(name, kind, source, scope values)`. `kind` is `expr` for one expression or
`template` for text with `{{ }}` parts (expr.py's syntax; when TEL's syntax is decided the sources
are translated and the names stay, so results stay comparable).
"""

from typing import Any

WORKSPACES = [{"name": f"ws{i}", "active": i % 3 == 0, "windows": i} for i in range(10)]
MANY = [{"name": f"w{i}", "active": i % 3 == 0, "windows": i} for i in range(100)]

SCOPE: dict[str, Any] = {
    "count": 7,
    "battery": 63,
    "charging": False,
    "volume": 0.4,
    "width": 400,
    "pad": 8,
    "offset": 3,
    "total": 1234.5,
    "n": 3,
    "state": "discharging",
    "title": "Terminal",
    "ws": WORKSPACES[0],
    "items": [10, 20, 30],
    "workspaces": WORKSPACES,
    "many": MANY,
}

WORKLOADS: list[tuple[str, str, str, dict[str, Any]]] = [
    ("name", "expr", "count", SCOPE),
    ("add", "expr", "count + 1", SCOPE),
    ("compare", "expr", "battery < 20 and not charging", SCOPE),
    ("conditional", "expr", "'low' if battery < 20 else 'ok'", SCOPE),
    ("arithmetic", "expr", "(width - 2 * pad) / 3 + offset", SCOPE),
    ("attribute", "expr", "ws.name", SCOPE),
    ("subscript", "expr", "items[0] + items[-1]", SCOPE),
    ("fstring", "expr", "f'{battery}% ({state})'", SCOPE),
    ("call", "expr", "format_number(total, 1)", SCOPE),
    ("call-two", "expr", "pluralize(n, 'window') + ' on ' + title.upper()", SCOPE),
    ("comprehension-10", "expr", "[w.name for w in workspaces if w.active]", SCOPE),
    ("comprehension-100", "expr", "[w.name for w in many if w.active]", SCOPE),
    ("sum-100", "expr", "sum([w.windows for w in many])", SCOPE),
    ("template", "template", "Battery {{ battery }}% ({{ state }}), {{ count }} items", SCOPE),
    (
        "long",
        "expr",
        "'critical' if battery < 10 else 'low' if battery < 20 else 'charging' if charging "
        "else f'{round(battery / 10) * 10}%'",
        SCOPE,
    ),
]

# A realistic set of bindings over a few inputs, for the "one input changed" scenario.
BINDINGS = [
    "battery < 20",
    "'low' if battery < 20 else 'ok'",
    "f'{battery}%'",
    "battery / 100",
    "not charging and battery < 50",
    "'charging' if charging else 'idle'",
    "volume * 100",
    "f'{round(volume * 100)}%'",
    "volume == 0",
    "width - 2 * pad",
    "(width - 2 * pad) / 3",
    "pad * 2",
    "offset + 1",
    "format_number(total, 1)",
    "title.upper()",
    "len(title)",
    "count + 1",
    "pluralize(count, 'item')",
    "sum(items)",
    "[w.name for w in workspaces if w.active]",
]
