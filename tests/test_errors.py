import ast
import pickle

import pytest

from tel import (
    Origin,
    TelError,
    TelEvaluationError,
    TelLimitError,
    TelSyntaxError,
    TelVersionError,
)
from tel._spans import did_you_mean, node_span

ALL_ERRORS = [TelError, TelSyntaxError, TelEvaluationError, TelLimitError, TelVersionError]


def error(**kw):
    kw.setdefault("code", "test")
    kw.setdefault("line", 1)
    kw.setdefault("column", 1)
    return TelError("boom", **kw)


# -- Origin ---------------------------------------------------------------------------------------


def test_origin_is_one_based_immutable_and_comparable():
    origin = Origin("A.yaml", 14, 7)
    assert (origin.file, origin.line, origin.column) == ("A.yaml", 14, 7)
    assert origin == Origin("A.yaml", 14, 7) and hash(origin) == hash(Origin("A.yaml", 14, 7))
    with pytest.raises(AttributeError):
        origin.line = 2  # type: ignore[misc]
    assert Origin() == Origin(None, 1, 1)


@pytest.mark.parametrize("line, column", [(0, 1), (1, 0), (-1, 1), (1, -5)])
def test_origin_refuses_positions_below_one(line, column):
    with pytest.raises(ValueError, match="1-based"):
        Origin("A.yaml", line, column)


@pytest.mark.parametrize("bad", [1.0, "1", None, True])
def test_origin_refuses_a_line_or_column_that_is_not_an_int(bad):
    with pytest.raises(TypeError):
        Origin("A.yaml", bad, 1)
    with pytest.raises(TypeError):
        Origin("A.yaml", 1, bad)


def test_origin_refuses_a_file_that_is_not_text():
    with pytest.raises(TypeError):
        Origin(5, 1, 1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "prefix, line, column",
    [
        ("", 14, 7),
        ("  ", 14, 9),
        ("\n", 15, 1),
        ("\n  ", 15, 3),
        ("a\nbc", 15, 3),
        ("x\n\n   ", 16, 4),
    ],
)
def test_origin_advance_moves_past_the_text_before_an_expression(prefix, line, column):
    moved = Origin("A.yaml", 14, 7).advance(prefix)
    assert (moved.file, moved.line, moved.column) == ("A.yaml", line, column)


# -- positions ------------------------------------------------------------------------------------


def test_without_an_origin_the_positions_are_the_texts():
    e = error(source="a +\n  b", line=2, column=3, end_column=4)
    assert (e.line, e.column, e.end_column, e.file) == (2, 3, 4, None)
    assert str(e) == "2:3: boom"


def test_on_the_first_line_the_column_is_shifted_by_the_origin():
    e = error(source="count + cnt", line=1, column=9, end_column=12, origin=Origin("V.yaml", 14, 8))
    assert (e.file, e.line, e.column, e.end_column) == ("V.yaml", 14, 16, 19)
    assert (e.text_line, e.text_column) == (1, 9)
    assert str(e) == "V.yaml:14:16: boom"


def test_on_a_later_line_the_line_is_shifted_and_the_column_is_the_texts():
    e = error(source="(1 +\n  oops)", line=2, column=3, origin=Origin("V.yaml", 5, 5))
    assert (e.line, e.column) == (6, 3)


def test_an_origin_without_a_file_still_shifts_the_positions():
    e = error(source="x", line=1, column=1, origin=Origin(None, 3, 4))
    assert (e.file, e.line, e.column) == (None, 3, 4)
    assert str(e) == "3:4: boom"


def test_the_hint_is_part_of_the_text_and_a_field():
    e = error(hint="did you mean 'count'")
    assert e.hint == "did you mean 'count'"
    assert str(e) == "1:1: boom (did you mean 'count')"


def test_a_code_is_required_and_is_a_short_identifier():
    with pytest.raises(TypeError):
        TelError("boom")  # type: ignore[call-arg]
    assert error(code="private-name").code == "private-name"


def test_an_error_before_any_parsing_has_no_position():
    e = TelError("boom", code="x")
    assert (e.line, e.column, e.end_column, e.file) == (None, None, None, None)
    assert str(e) == "boom" and e.render() == "boom"


def test_a_line_without_a_column_is_refused():
    with pytest.raises(ValueError, match="together"):
        TelError("boom", code="x", line=1)
    with pytest.raises(ValueError, match="together"):
        TelError("boom", code="x", column=1)


def test_positions_below_one_are_refused():
    with pytest.raises(ValueError):
        error(line=0)
    with pytest.raises(ValueError):
        error(column=0)


# -- render ---------------------------------------------------------------------------------------


def test_render_draws_a_caret_under_the_span():
    e = error(source="count + cnt", line=1, column=9, end_column=12, origin=Origin("V.yaml", 14, 8))
    assert e.render() == "V.yaml:14:16: boom\n    count + cnt\n            ^^^"


def test_render_uses_one_caret_when_the_span_is_unknown_or_ends_the_line():
    assert error(source="a + b", column=3).render().endswith("    a + b\n      ^")


def test_render_picks_the_line_of_a_multi_line_expression():
    e = error(source="(1 +\n  oops)", line=2, column=3, end_column=7)
    assert e.render().splitlines()[1:] == ["      oops)", "      ^^^^"]


def test_render_keeps_tabs_so_the_caret_lines_up():
    e = error(source="\tx + y", line=1, column=6, end_column=7)
    lines = e.render().splitlines()
    assert lines[1] == "    \tx + y" and lines[2] == "    \t    ^"


def test_render_survives_an_empty_source_and_a_line_past_the_end():
    assert error(source="").render().endswith("^")
    assert error(source="a", line=9, column=1).render().count("\n") == 2


# -- the class hierarchy --------------------------------------------------------------------------


def test_every_error_is_a_value_error_and_a_tel_error():
    for cls in ALL_ERRORS:
        assert issubclass(cls, TelError) and issubclass(cls, ValueError)
    for cls in (TelSyntaxError, TelEvaluationError, TelLimitError, TelVersionError):
        assert cls is not TelError and cls.__mro__[1] is TelError


@pytest.mark.parametrize("cls", ALL_ERRORS)
def test_an_error_survives_pickling_with_every_field(cls):
    original = cls(
        "boom",
        code="x-y",
        source="a +\n b",
        line=2,
        column=2,
        end_column=3,
        hint="did you mean 'b'",
        origin=Origin("V.yaml", 5, 5),
    )
    copy = pickle.loads(pickle.dumps(original))
    assert type(copy) is cls
    for field in ("message", "code", "source", "hint", "file", "line", "column", "end_column"):
        assert getattr(copy, field) == getattr(original, field)
    assert str(copy) == str(original)


# -- the positions of syntax-tree nodes -----------------------------------------------------------


def node(source: str, index: int = -1) -> ast.expr:
    return [n for n in ast.walk(ast.parse(source, mode="eval")) if isinstance(n, ast.Name)][index]


def test_node_span_is_one_based_with_an_exclusive_end():
    source = "count + cnt"
    cnt = [n for n in ast.walk(ast.parse(source, mode="eval")) if getattr(n, "id", "") == "cnt"][0]
    assert node_span(source, cnt) == (1, 9, 12)


def test_node_span_counts_characters_not_utf8_bytes():
    source = "'é' + x"  # ast reports x at byte 7; it is the 7th character, so column 7 (1-based)
    x = [n for n in ast.walk(ast.parse(source, mode="eval")) if getattr(n, "id", "") == "x"][0]
    assert x.col_offset == 7  # the byte offset ast reports
    assert node_span(source, x) == (1, 7, 8)


def test_node_span_for_a_node_on_a_later_line_and_for_a_multi_line_node():
    source = "(1 +\n  oops)"
    oops = [n for n in ast.walk(ast.parse(source, mode="eval")) if getattr(n, "id", "") == "oops"][
        0
    ]
    assert node_span(source, oops) == (2, 3, 7)
    whole = ast.parse(source, mode="eval").body
    assert node_span(source, whole) == (1, 2, None)  # spans two lines: no single-line end


@pytest.mark.parametrize(
    "source, case_origin, expected",
    [
        # the position cases of expr.py, with columns 1-based (expr.py's are 0-based)
        ("count + cnt", Origin("Main_View.yaml", 14, 8), (14, 16)),
        ("(1 +\n  oops)", Origin("A_View.yaml", 5, 5), (6, 3)),
    ],
)
def test_the_reference_position_cases_map_into_the_file(source, case_origin, expected):
    name = [
        n
        for n in ast.walk(ast.parse(source, mode="eval"))
        if getattr(n, "id", "") in ("cnt", "oops")
    ][0]
    line, column, end = node_span(source, name)
    e = error(source=source, line=line, column=column, end_column=end, origin=case_origin)
    assert (e.line, e.column) == expected


def test_a_leading_space_is_accounted_for_by_advancing_the_origin():
    origin = Origin("A_View.yaml", 2, 11).advance("  ")  # "  nope": the text starts two columns in
    e = error(source="nope", line=1, column=1, origin=origin)
    assert (e.line, e.column) == (2, 13)  # expr.py: 12, 0-based


# -- suggestions ----------------------------------------------------------------------------------


def test_did_you_mean_names_the_nearest_names():
    assert did_you_mean("cnt", ["count", "items"]) == "did you mean 'count'"
    assert did_you_mean("titel", ["title", "titles", "x"]) == "did you mean 'title' or 'titles'"
    assert did_you_mean("zzz", ["count"]) is None
    assert did_you_mean("a", []) is None


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_node_span_and_render_agree_with_ast_on_every_kind_of_line_break(newline):
    source = f"(1 +{newline}  oops)"
    oops = [n for n in ast.walk(ast.parse(source, mode="eval")) if getattr(n, "id", "") == "oops"][
        0
    ]
    line, column, end = node_span(source, oops)
    assert (line, column, end) == (2, 3, 7)
    rendered = error(source=source, line=line, column=column, end_column=end).render()
    assert rendered.splitlines()[1:] == ["      oops)", "      ^^^^"]


def test_a_form_feed_is_not_a_line_break_for_ast_so_it_is_not_one_here():
    source = "(1 +\x0c oops)"
    oops = [n for n in ast.walk(ast.parse(source, mode="eval")) if getattr(n, "id", "") == "oops"][
        0
    ]
    assert node_span(source, oops)[0] == 1
