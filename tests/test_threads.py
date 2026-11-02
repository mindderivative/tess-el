"""Many threads at once (free-threaded Python, and any build): shared compiled objects, the reader's
warnings lock, the repeater's state. Every thread's results must equal a single-threaded run.

On a free-threaded build (`python3.14t`, GIL off) these are real races; on a build with the GIL they
still catch a lock that is held too briefly or state that is shared by mistake.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import tel
from tel import MapScope, RepeaterState, TelError

THREADS = 8
ROUNDS = 150
LANG = "0.1"


def run_threads(work):
    """Run `work(index)` in THREADS threads that all start together; return their results."""
    barrier = threading.Barrier(THREADS)

    def start(index):
        barrier.wait()
        return work(index)

    with ThreadPoolExecutor(THREADS) as pool:
        return list(pool.map(start, range(THREADS)))


TEXTS = [
    "a + b * 2",
    "a < b ? 'lo' : 'hi'",
    "[x * a for x in xs if x > 1]",
    "sum(xs) + len(s)",
    "f'{a:>4}|{s!r}'",
    "d.k + d.j[0]",
    "{k: v for k, v in pairs}",
    "'it\\'s' + s",  # a backslash: the reader takes its warnings lock
    "a if b else 1if 1else 2",  # a number against a keyword: also takes it
    "max(xs) - min(xs)",
]
VALUES = {
    "a": 3,
    "b": 5,
    "s": "text",
    "xs": [1, 2, 3, 4],
    "d": {"k": 1, "j": [9]},
    "pairs": [("p", 1), ("q", 2)],
}


def evaluate(text):
    try:
        return repr(tel.compile_expression(text, language=LANG).evaluate(MapScope(VALUES)))
    except TelError as error:
        return error.code


EXPECTED = [evaluate(text) for text in TEXTS]


def test_threads_compiling_and_evaluating_different_text_get_the_single_threaded_results():
    def work(_):
        return [evaluate(text) for _ in range(ROUNDS) for text in TEXTS]

    for result in run_threads(work):
        assert result == EXPECTED * ROUNDS


def test_threads_sharing_one_compiled_expression_get_the_same_value_and_reads():
    expression = tel.compile_expression("[x * a for x in xs] + [b if flag else 0]", language=LANG)
    scope = MapScope({**VALUES, "flag": True})
    want = expression.evaluate(scope)
    want_reads = expression.evaluate_tracked(scope).reads

    def work(_):
        for _ in range(ROUNDS * 4):
            assert expression.evaluate(scope) == want
            assert expression.evaluate_tracked(scope).reads == want_reads
            assert expression.canonical == expression.canonical

    run_threads(work)


def test_threads_sharing_one_template_and_one_condition():
    template = tel.compile_template(
        "a={{ a }} b={{ b ? 'y' : 'n' }} s={{ s.upper() }}", language=LANG
    )
    condition = tel.compile_condition("a < b and xs", language=LANG)
    scope = MapScope(VALUES)

    def work(_):
        for _ in range(ROUNDS * 4):
            assert template.evaluate(scope) == "a=3 b=y s=TEXT"
            assert condition.holds(scope) is True

    run_threads(work)


def test_threads_sharing_one_repeater_and_one_state_get_the_same_reconciliation():
    repeater = tel.compile_repeater_parts("w", "ws", key="w.id", name="W", language=LANG)
    first = repeater.reconcile(MapScope({"ws": [{"id": i} for i in range(5)]}), RepeaterState())
    scope = MapScope({"ws": [{"id": i} for i in (4, 9, 0, 1, 2, 3)]})
    want = repeater.reconcile(scope, first.state)
    shape = lambda r: ([(e.key, e.name, e.status) for e in r.entries], r.moved, r.removed)  # noqa: E731

    def work(_):
        for _ in range(ROUNDS):
            got = repeater.reconcile(scope, first.state)
            assert shape(got) == shape(want)
            assert got.state.keys == want.state.keys
            tracked = repeater.reconcile_tracked(scope, first.state)
            assert shape(tracked.value) == shape(want)

    run_threads(work)
    assert first.state.keys == (0, 1, 2, 3, 4)  # nobody changed the state they shared


def test_threads_filling_and_reading_text_with_placeholders():
    def work(index):
        out = []
        for round_ in range(ROUNDS):
            n = index * 1000 + round_
            text = tel.fill("battery < $n and name in $names", {"n": n, "names": ["a", str(n)]})
            expression = tel.compile_expression(text, language=LANG)
            out.append((n, expression.canonical, text))
        return out

    for result in run_threads(work):
        for n, canonical, text in result:
            assert canonical == f"battery < {n} and name in ['a', '{n}']"
            assert text == f"battery < {n} and name in ['a', '{n}']"


def test_threads_that_make_syntax_errors_while_others_read_text_with_a_warning():
    """The warnings filter is process-wide: one thread's `ast.parse` must not change another's."""
    noisy = ["'a\\d'", "1if 1else 2", "x if 1else 2"]
    broken = ["a +", "(", "x ? y", "f'{'", "1 +* 2"]

    def work(index):
        for round_ in range(ROUNDS):
            text = noisy[round_ % len(noisy)] if index % 2 == 0 else broken[round_ % len(broken)]
            try:
                tel.compile_expression(text, language=LANG)
            except TelError as error:
                assert index % 2 == 1 or error.code, text
        return True

    assert all(run_threads(work))


def test_a_hundred_threads_one_after_another_leave_no_state_behind():
    expression = tel.compile_expression("a + b", language=LANG)
    results = []

    def one():
        results.append(expression.evaluate(MapScope({"a": 1, "b": 2})))

    threads = [threading.Thread(target=one) for _ in range(100)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [3] * 100


@pytest.mark.parametrize("text", ["a + b", "[x for x in xs]", "f'{a}'"])
def test_threads_that_hit_a_limit_get_the_same_error(text):
    limits = tel.Limits(max_steps=3)

    def work(_):
        codes = set()
        for _ in range(ROUNDS):
            try:
                tel.compile_expression(text, language=LANG, limits=limits).evaluate(
                    MapScope(VALUES)
                )
            except TelError as error:
                codes.add(error.code)
        return codes

    results = run_threads(work)
    assert all(codes == results[0] for codes in results)
