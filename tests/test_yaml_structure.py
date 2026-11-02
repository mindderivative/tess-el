"""Conditions and repeaters from YAML text (requirement T8, step 5 phase 5).

The Shell owns the file format; `walk` below is a small stand-in for it, written for these tests:
it reads the `if:`, `elif:`, `else:`, `for:` and `key:` keys of a loaded file and calls TEL for
every decision. It proves that what TEL gives (`select`, `reconcile`, the names, the origins) is
enough to build the tree from plain YAML, and that the YAML traps the docs name are real.
"""

import textwrap

import pytest
import yaml

import tel
from tel import MapScope, Origin, RepeaterState, TelError

LANG = "0.1"

FILE = """
shell: "0.1"
type: Shell
children:
  - name: Bar
    children:
      - if: battery < 20
        label: low
      - elif: battery < 60
        label: half
      - else:
        label: full
      - for: w in workspaces
        key: w.id
        name: Workspace
        label: "{{ w.name }}"
        children:
          - if: w.windows > 5
            label: busy
          - elif: w.windows > 0
            label: some
          - else:
            label: empty
      - for: i, t in enumerate(tray)
        key: t.app
        name: Tray
        label: "{{ i }}:{{ t.app }}"
"""


def load(text):
    return yaml.safe_load(textwrap.dedent(text))


def ws(*triples):
    return [{"id": i, "name": n, "windows": w} for i, n, w in triples]


def walk(nodes, scope, states, trail=()):
    """Build the tree for `nodes` in `scope`. `states` maps a trail to the repeater's state."""
    out, i = [], 0
    while i < len(nodes):
        node = nodes[i]
        i += 1
        if "for" in node:
            repeater = tel.compile_repeater(
                node["for"], key=str(node["key"]), name=node["name"], language=LANG
            )
            where = trail + (node["name"],)
            result = repeater.reconcile(scope, states.get(where, RepeaterState()))
            states[where] = result.state
            for entry in result.entries:
                child = entry.scope(scope)
                out.append(realise(node, child, states, trail + (entry.name,), entry.name))
        elif "if" in node:
            chain = [node]
            while i < len(nodes) and ("elif" in nodes[i] or "else" in nodes[i]):
                chain.append(nodes[i])
                i += 1
            tests = [
                tel.compile_condition(str(n.get("if", n.get("elif"))), language=LANG)
                for n in chain
                if "else" not in n
            ]
            chosen = tel.select(tests, scope)
            if chosen is None and "else" in chain[-1]:
                chosen = len(tests)  # the `else` is the member after the conditions
            if chosen is not None:
                out.append(realise(chain[chosen], scope, states, trail))
        else:
            out.append(realise(node, scope, states, trail))
    return out


def realise(node, scope, states, trail, name=None):
    made = {"name": name or node.get("name")}
    if "label" in node:
        text = str(node["label"])
        template = tel.compile_template(text, language=LANG)
        made["label"] = text if template is None else template.evaluate(scope)
    if "children" in node:
        made["children"] = walk(node["children"], scope, states, trail)
    return made


def bar(tree):
    return tree[0]["children"]


def shell(text=FILE):
    return load(text)["children"]


def labels(tree):
    return [n["label"] for n in bar(tree)]


STATE = {
    "battery": 80,
    "workspaces": ws((10, "one", 0), (11, "two", 3), (12, "three", 9)),
    "tray": [{"app": "wifi"}, {"app": "vol"}],
}


# -- the file is plain YAML -----------------------------------------------------------------------


def test_the_directives_load_as_ordinary_yaml_keys():
    nodes = shell()[0]["children"]
    assert [list(n)[0] for n in nodes] == ["if", "elif", "else", "for", "for"]
    assert nodes[0]["if"] == "battery < 20"  # a plain string, with no TEL syntax needed
    assert nodes[2] == {"else": None, "label": "full"}
    assert nodes[3]["for"] == "w in workspaces" and nodes[3]["key"] == "w.id"
    assert nodes[4]["for"] == "i, t in enumerate(tray)"


# -- conditions -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("battery", "label"),
    [(5, "low"), (19, "low"), (20, "half"), (59, "half"), (60, "full"), (100, "full")],
)
def test_the_first_condition_that_holds_picks_the_branch_and_else_is_the_rest(battery, label):
    tree = walk(shell(), MapScope({**STATE, "battery": battery}), {})
    assert labels(tree)[0] == label
    assert [n for n in bar(tree) if n["label"] in ("low", "half", "full")] == [bar(tree)[0]]


def test_a_chain_with_no_else_may_give_nothing():
    nodes = load("""
        - if: a
          label: A
        - elif: b
          label: B
    """)
    assert walk(nodes, MapScope({"a": 0, "b": 0}), {}) == []
    assert [n["label"] for n in walk(nodes, MapScope({"a": 0, "b": 1}), {})] == ["B"]


def test_a_condition_after_the_winner_is_never_read():
    nodes = load("""
        - if: a
          label: A
        - elif: missing_name
          label: B
    """)
    assert [n["label"] for n in walk(nodes, MapScope({"a": 1}), {})] == ["A"]


# -- repeaters ------------------------------------------------------------------------------------


def test_a_repeater_makes_one_entry_per_item_with_its_own_children_and_scope():
    tree = walk(shell(), MapScope(STATE), {})
    spaces = [n for n in bar(tree) if (n["name"] or "").startswith("Workspace_")]
    assert [(n["name"], n["label"]) for n in spaces] == [
        ("Workspace_0001", "one"),
        ("Workspace_0002", "two"),
        ("Workspace_0003", "three"),
    ]
    assert [[c["label"] for c in n["children"]] for n in spaces] == [["empty"], ["some"], ["busy"]]


def test_a_header_with_two_names_reads_the_position_and_the_item():
    tree = walk(shell(), MapScope(STATE), {})
    tray = [n for n in bar(tree) if (n["name"] or "").startswith("Tray_")]
    assert [n["label"] for n in tray] == ["0:wifi", "1:vol"]


def test_a_second_load_adds_removes_and_reorders_with_stable_names():
    states = {}
    first = walk(shell(), MapScope(STATE), states)
    later = {
        **STATE,
        "workspaces": ws((12, "three", 9), (13, "four", 1), (10, "one", 7)),  # 11 gone, 13 new
    }
    second = walk(shell(), MapScope(later), states)

    def names(tree):
        return {n["name"]: n["label"] for n in bar(tree) if (n["name"] or "").startswith("W")}

    assert names(first) == {
        "Workspace_0001": "one",
        "Workspace_0002": "two",
        "Workspace_0003": "three",
    }
    assert names(second) == {
        "Workspace_0003": "three",
        "Workspace_0004": "four",
        "Workspace_0001": "one",
    }
    one = next(n for n in bar(second) if n["name"] == "Workspace_0001")
    assert [c["label"] for c in one["children"]] == ["busy"]  # its children saw the new value


def test_the_reconciliation_of_a_second_load_says_what_happened():
    repeater = tel.compile_repeater("w in workspaces", key="w.id", name="W", language=LANG)
    first = repeater.reconcile(MapScope(STATE), RepeaterState())
    after = {"workspaces": ws((12, "x", 0), (13, "y", 0), (10, "z", 0))}
    second = repeater.reconcile(MapScope(after), first.state)
    assert [(e.key, e.status) for e in second.entries] == [(12, "kept"), (13, "new"), (10, "kept")]
    assert second.removed == (11,)
    assert second.moved == (12,)  # 12 and 10 swapped places: 10 was earlier, so 10 stays


def test_repeaters_inside_repeaters_keep_separate_states():
    nodes = load("""
        - for: g in groups
          key: g.id
          name: Group
          children:
            - for: m in g.members
              key: m
              name: Member
              label: "{{ m }}"
    """)
    states = {}
    scope = {"groups": [{"id": "a", "members": ["x", "y"]}, {"id": "b", "members": ["x"]}]}
    first = walk(nodes, MapScope(scope), states)
    assert [[m["name"] for m in g["children"]] for g in first] == [
        ["Member_0001", "Member_0002"],
        ["Member_0001"],  # the same key `x` in another group has its own number
    ]
    scope["groups"][0]["members"] = ["y", "z"]
    second = walk(nodes, MapScope(scope), states)
    assert [m["name"] for m in second[0]["children"]] == ["Member_0002", "Member_0003"]


# -- positions in the file (T6) -------------------------------------------------------------------


def scalar(text, key, which=0):
    """The loaded node of the `which`-th scalar value for `key`: YAML knows where it is."""
    found = []

    def visit(node):
        if isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                if (
                    isinstance(k, yaml.ScalarNode)
                    and k.value == key
                    and isinstance(v, yaml.ScalarNode)
                ):
                    found.append(v)
                visit(v)
        elif isinstance(node, yaml.SequenceNode):
            for v in node.value:
                visit(v)

    visit(yaml.compose(text))
    return found[which]


def origin_of(node, file="shell.yaml"):
    return Origin(file, node.start_mark.line + 1, node.start_mark.column + 1)


def test_an_error_in_a_condition_points_at_its_place_in_the_file():
    text = textwrap.dedent("""\
        shell: "0.1"
        children:
          - if: battery < 20 and missing
            label: low
    """)
    node = scalar(text, "if")
    condition = tel.compile_condition(node.value, language=LANG, origin=origin_of(node))
    with pytest.raises(TelError) as raised:
        condition.holds(MapScope({"battery": 1}))
    assert (raised.value.file, raised.value.line, raised.value.column) == ("shell.yaml", 3, 26)
    assert text.splitlines()[2][raised.value.column - 1 :].startswith("missing")


def test_errors_in_a_header_and_in_its_key_point_at_their_own_scalars():
    text = textwrap.dedent("""\
        children:
          - for: w in workspaces
            key: w.nope
            name: W
    """)
    header, key = scalar(text, "for"), scalar(text, "key")
    repeater = tel.compile_repeater(
        header.value,
        key=key.value,
        name="W",
        language=LANG,
        origin=origin_of(header),
        key_origin=origin_of(key),
    )
    with pytest.raises(TelError) as raised:
        repeater.items(MapScope({"workspaces": [{"id": 1}]}))
    assert (raised.value.line, raised.value.column) == (3, 10)  # `w.nope` on the `key:` line
    with pytest.raises(TelError) as raised:
        repeater.items(MapScope({}))
    assert (raised.value.line, raised.value.column) == (2, 15)  # `workspaces` after `for: w in `


def test_a_bad_header_points_into_the_file():
    text = "children:\n  - for: w of workspaces\n    key: w\n"
    header = scalar(text, "for")
    with pytest.raises(tel.TelSyntaxError) as raised:
        tel.compile_repeater(
            header.value, key="w", name="W", language=LANG, origin=origin_of(header)
        )
    assert (raised.value.file, raised.value.line, raised.value.column) == ("shell.yaml", 2, 10)


# -- the YAML traps -------------------------------------------------------------------------------


def test_a_colon_and_space_in_a_condition_has_to_be_quoted_in_yaml_as_the_docs_say():
    with pytest.raises(yaml.YAMLError):
        load("- if: ok ? a : b\n  label: x\n")
    nodes = load("- if: 'ok ? 1 : 0'\n  label: x\n")
    assert tel.compile_condition(nodes[0]["if"], language=LANG).holds(MapScope({"ok": True}))


def test_yaml_turns_an_unquoted_number_or_bool_into_a_non_string_so_the_host_must_quote():
    nodes = load("- if: true\n  label: x\n- if: 1\n  label: y\n- for: w in xs\n  key: 7\n")
    assert nodes[0]["if"] is True and nodes[1]["if"] == 1 and nodes[2]["key"] == 7
    with pytest.raises(TypeError, match="str"):
        tel.compile_condition(nodes[0]["if"], language=LANG)
    with pytest.raises(TypeError, match="str"):
        tel.compile_repeater("w in xs", key=nodes[2]["key"], name="W", language=LANG)
