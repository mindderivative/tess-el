"""A repeater from separate pieces (step 6 phase 4): the Shell's `for item in {{ }} key {{ }}`."""

import pytest

import tel
from tel import Limits, MapScope, Origin, TelError, TelLimitError, TelSyntaxError

LANG = "0.1"


def parts(names="w", items="xs", key="w", **kw):
    kw.setdefault("name", "W")
    return tel.compile_repeater_parts(names, items, key=key, language=LANG, **kw)


def header(h="w in xs", key="w", **kw):
    kw.setdefault("name", "W")
    return tel.compile_repeater(h, key=key, language=LANG, **kw)


def run(repeater, **values):
    result = repeater.reconcile(MapScope(values), tel.RepeaterState())
    return [(e.key, e.name, e.value) for e in result.entries]


# -- it is the repeater the header form makes -----------------------------------------------------


@pytest.mark.parametrize(
    ("names", "items", "key", "values"),
    [
        ("w", "xs", "w", {"xs": [3, 1, 2]}),
        ("i, w", "enumerate(xs)", "(i, w)", {"xs": "abc"}),
        ("  w  ", "  [x for x in xs if x > 1]  ", "w", {"xs": [1, 2, 3]}),
        ("w", "box.rows", "w.id", {"box": type("B", (), {"rows": [{"id": 5}, {"id": 6}]})()}),
        ("_", "xs", "1 if False else 0", {"xs": [1]}),
        ("w", "range(3)", "w * 2", {}),
    ],
)
def test_the_parts_form_gives_the_repeater_the_header_form_gives(names, items, key, values):
    a = parts(names, items, key)
    b = header(f"{names} in {items}", key)
    assert run(a, **values) == run(b, **values)
    assert a.targets == b.targets and a.name == b.name
    assert a.items(MapScope(values)) is not None
    assert [i.key for i in a.items(MapScope(values))] == [i.key for i in b.items(MapScope(values))]


def test_the_header_of_a_parts_repeater_is_the_text_as_if_it_were_written():
    assert parts("item", "tray.items").header == "item in tray.items"
    assert parts("  i ,  w ", "  enumerate(xs) \n").header == "i ,  w in enumerate(xs)"


def test_the_parts_form_builds_on_the_same_checks_as_the_header_form():
    # the same texts are refused the same way, with the same code, by either form
    for names in ("class", "_w", "a, a", "a.b", "(a, b)", "a, ", "", "  ", "1a", "*a"):
        with pytest.raises(TelSyntaxError) as one:
            parts(names, "xs")
        with pytest.raises(TelSyntaxError) as two:
            header(f"{names} in xs")
        assert one.value.code == two.value.code, names


# -- the names ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("names", "code", "needle"),
    [
        ("", "repeater-header", "empty"),
        ("   ", "repeater-header", "empty"),
        ("a.b", "repeater-header", "must be a name"),
        ("(a, b)", "repeater-header", "must be a name"),
        ("a b", "repeater-header", "must be a name"),
        ("a,", "repeater-header", "must be a name"),
        ("a in b", "repeater-header", "must be a name"),
        ("class", "repeater-header", "cannot be a name"),
        ("_w", "private-name", "private"),
        ("a, a", "repeater-header", "twice"),
    ],
)
def test_a_bad_names_text_is_a_syntax_error_with_its_own_code(names, code, needle):
    with pytest.raises(TelSyntaxError) as raised:
        parts(names, "xs")
    assert raised.value.code == code and needle in raised.value.message


def test_a_names_error_points_at_the_names_scalar_in_the_file():
    with pytest.raises(TelSyntaxError) as raised:
        parts("  a, a", "xs", names_origin=Origin("t.tdl", 4, 9))
    error = raised.value
    assert (error.file, error.line, error.column, error.end_column) == ("t.tdl", 4, 9 + 5, 9 + 6)
    with pytest.raises(TelSyntaxError) as raised:
        parts("a.b", "xs", names_origin=Origin("t.tdl", 4, 9))
    assert (raised.value.line, raised.value.column, raised.value.end_column) == (4, 9, 12)


def test_two_underscores_are_two_throwaway_names():
    assert parts("_, _", "xs").targets == ("_", "_")


def test_the_names_may_run_over_lines():
    assert parts("a,\n b", "xs").targets == ("a", "b")


# -- the list -------------------------------------------------------------------------------------


def test_an_error_in_the_list_points_at_the_list_scalar_not_the_names():
    r = parts("w", "1 / 0", names_origin=Origin("t.tdl", 3, 5), items_origin=Origin("t.tdl", 7, 20))
    with pytest.raises(TelError) as raised:
        r.items(MapScope({}))
    assert (raised.value.file, raised.value.line, raised.value.column) == ("t.tdl", 7, 20)


def test_a_syntax_error_in_the_list_is_positioned_inside_it():
    with pytest.raises(TelSyntaxError) as raised:
        parts("w", "a +", items_origin=Origin("t.tdl", 7, 20))
    assert (raised.value.file, raised.value.line) == ("t.tdl", 7)
    assert raised.value.column is not None and raised.value.column >= 20


def test_leading_space_in_the_list_text_moves_the_column_as_for_any_expression():
    r = parts("w", "   zzz", items_origin=Origin("t.tdl", 7, 20))
    with pytest.raises(TelError) as raised:
        r.items(MapScope({}))
    assert (raised.value.code, raised.value.column) == ("unknown-name", 23)


def test_an_empty_list_is_an_empty_expression_error_at_the_list_origin():
    for text in ("", "   "):
        with pytest.raises(TelSyntaxError) as raised:
            parts("w", text, items_origin=Origin("t.tdl", 7, 20))
        assert raised.value.code == "empty-expression"
        assert (raised.value.line, raised.value.column) == (7, 20 + len(text) - len(text.lstrip()))


@pytest.mark.parametrize("text", ["a for b in c", "x if y else", "w in", "in xs"])
def test_the_list_text_is_one_expression_not_a_header(text):
    with pytest.raises(TelSyntaxError):
        parts("w", text)  # a second `in` or a `for` is the list's own syntax


def test_a_list_with_in_inside_it_is_an_expression_like_any_other():
    r = parts("w", "[x for x in xs]", key="w")
    assert [k for k, *_ in run(r, xs=[4, 5])] == [4, 5]
    r = parts("w", "xs if 'a' in names else ys")
    assert [k for k, *_ in run(r, xs=[1], ys=[2], names="abc")] == [1]


# -- the key and the three origins are independent -------------------------------------------------


def test_each_piece_reports_its_own_origin():
    names, items, key = Origin("t.tdl", 1, 5), Origin("t.tdl", 2, 15), Origin("t.tdl", 3, 25)
    r = parts("w", "xs", key="w.nope", names_origin=names, items_origin=items, key_origin=key)
    with pytest.raises(TelError) as raised:
        r.items(MapScope({"xs": [{"id": 1}]}))
    assert (raised.value.line, raised.value.column) == (3, 25)
    with pytest.raises(TelError) as raised:
        r.items(MapScope({}))
    assert (raised.value.line, raised.value.column) == (2, 15)


def test_the_origins_are_optional_and_independent():
    r = parts("w", "xs", key="w + 1", items_origin=Origin("t.tdl", 2, 15))
    assert [k for k, *_ in run(r, xs=[1])] == [2]
    with pytest.raises(TelError) as raised:
        r.items(MapScope({"xs": ["a"]}))
    assert raised.value.file is None and raised.value.line == 1


# -- the checks the header form has too -----------------------------------------------------------


def test_the_name_the_language_the_limits_and_the_registrations_are_checked_and_carried():
    for bad in ("", "1a", "class", "_x"):
        with pytest.raises(ValueError):
            parts(name=bad)
    with pytest.raises(TypeError):
        parts(name=None)
    with pytest.raises(tel.TelVersionError):
        tel.compile_repeater_parts("w", "xs", key="w", name="W", language="9.9")
    with pytest.raises(TelLimitError) as raised:
        parts("w", "xs", limits=Limits(max_source=1), key="w")
        parts("w", "xx", limits=Limits(max_source=1))
    assert raised.value.code == "limit-source"
    r = parts("w", "xs", key="double(w)", functions={"double": lambda n: n * 2})
    assert [k for k, *_ in run(r, xs=[1, 2])] == [2, 4]

    class Price:
        pass

    r = parts("w", "xs", key="w.tag()", methods={Price: {"tag": lambda p: "t"}})
    assert [k for k, *_ in run(r, xs=[Price()])] == ["t"]


def test_the_names_over_max_source_are_refused_whole_before_they_are_read():
    limits = Limits(max_source=5)
    parts("abcde", "x", key="1", limits=Limits(max_source=5))
    with pytest.raises(TelLimitError) as raised:
        parts("abcdef", "x", limits=limits)
    assert raised.value.code == "limit-source"
    with pytest.raises(TelLimitError):
        parts("a, a, " * 100_000, "x", limits=Limits(max_source=10))


def test_arguments_of_the_wrong_type_are_type_errors():
    bad: list[tuple[object, object, object]] = [(5, "xs", "w"), ("w", 5, "w"), ("w", "xs", 5)]
    for names, items, key in bad:
        with pytest.raises(TypeError):
            tel.compile_repeater_parts(names, items, key=key, name="W", language=LANG)  # type: ignore[arg-type]
    for field in ("names_origin", "items_origin", "key_origin"):
        with pytest.raises(TypeError):
            parts("w", "xs", **{field: "x"})
    with pytest.raises(TypeError):
        tel.compile_repeater_parts("w", "xs", language=LANG, name="W")  # type: ignore[call-arg]


def test_a_str_subclass_is_read_as_plain_text():
    class Text(str):
        def __str__(self):
            raise RuntimeError("host code ran")

        def strip(self, *a):
            raise RuntimeError("host code ran")

    r = tel.compile_repeater_parts(Text(" w "), Text("xs"), key=Text("w"), name="W", language=LANG)
    assert r.targets == ("w",) and r.header == "w in xs"
