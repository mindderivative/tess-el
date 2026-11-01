"""Reconciliation (step 5, phase 4): the entries of a list against the state of the last call."""

import copy
import pickle
import random

import pytest

import tel
from tel import (
    Entry,
    Limits,
    MapScope,
    Reconciliation,
    RepeaterState,
    TelEvaluationError,
    TelLimitError,
    Tracked,
)


def rep(header="w in xs", key="w", **kw):
    kw.setdefault("name", "W")
    return tel.compile_repeater(header, key=key, language="0.1", **kw)


def scope(**values):
    return MapScope(values)


def go(items, state=None, repeater=None):
    """Reconcile a list of keys (the items are their own keys)."""
    return (repeater or rep()).reconcile(scope(xs=list(items)), state or RepeaterState())


def names(result):
    return [entry.name for entry in result.entries]


# -- the first call -------------------------------------------------------------------------------


def test_the_first_call_makes_every_entry_new_and_numbers_them_from_one():
    result = go("abc")
    assert isinstance(result, Reconciliation)
    assert [(e.index, e.key, e.value, e.name, e.status) for e in result.entries] == [
        (0, "a", "a", "W_0001", "new"),
        (1, "b", "b", "W_0002", "new"),
        (2, "c", "c", "W_0003", "new"),
    ]
    assert result.moved == () and result.removed == ()
    assert result.state.keys == ("a", "b", "c")
    assert all(isinstance(e, Entry) for e in result.entries)


def test_an_empty_list_gives_an_empty_result_and_an_empty_state():
    result = go([])
    assert result.entries == () and result.moved == () and result.removed == ()
    assert result.state.keys == ()


def test_the_same_list_again_keeps_every_entry_with_its_name():
    first = go("abc")
    again = go("abc", first.state)
    assert [(e.key, e.name, e.status) for e in again.entries] == [
        ("a", "W_0001", "kept"),
        ("b", "W_0002", "kept"),
        ("c", "W_0003", "kept"),
    ]
    assert again.moved == () and again.removed == ()


# -- what changes ---------------------------------------------------------------------------------


def test_a_new_key_takes_the_next_number_and_the_others_keep_theirs():
    first = go("abc")
    result = go("xabc", first.state)
    assert [(e.key, e.name, e.status) for e in result.entries] == [
        ("x", "W_0004", "new"),
        ("a", "W_0001", "kept"),
        ("b", "W_0002", "kept"),
        ("c", "W_0003", "kept"),
    ]
    assert result.moved == ()  # nothing kept changed its place relative to the others


def test_removed_keys_are_listed_in_their_old_order():
    first = go("abcde")
    result = go("bd", first.state)
    assert result.removed == ("a", "c", "e")
    assert [e.name for e in result.entries] == ["W_0002", "W_0004"]
    assert result.state.keys == ("b", "d")


def test_a_number_is_never_used_twice_even_for_the_last_key_removed():
    first = go("abc")
    second = go("ab", first.state)  # c (3) is gone
    third = go("abd", second.state)
    assert names(third) == ["W_0001", "W_0002", "W_0004"]  # d is 4, not 3


def test_a_key_that_goes_away_and_comes_back_is_a_new_entry_with_a_new_number():
    first = go("ab")
    second = go("b", first.state)
    third = go("ab", second.state)
    assert [(e.key, e.name, e.status) for e in third.entries] == [
        ("a", "W_0003", "new"),
        ("b", "W_0002", "kept"),
    ]
    assert third.removed == ()


def test_a_key_that_is_removed_and_added_in_one_call_cannot_happen_it_is_just_kept():
    first = go("ab")
    assert go("ba", first.state).removed == ()


def test_the_number_has_four_digits_and_grows_past_them():
    r = rep("w in range(10000)", "w")
    result = r.reconcile(scope(), RepeaterState())
    assert result.entries[8].name == "W_0009"
    assert result.entries[9998].name == "W_9999"
    assert result.entries[9999].name == "W_10000"


# -- moved ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "moved"),
    [
        ("abcde", "eabcd", ("e",)),  # one to the front: only it moves
        ("abcde", "bcdea", ("a",)),  # one to the back
        ("abcde", "abcde", ()),
        ("abcde", "xaybzcdew", ()),  # new keys do not move anything
        ("abcde", "abde", ()),  # removal does not move anything
        ("abc", "cba", ("c", "b")),  # a reversal keeps one in place: the earliest old one
        ("abcdef", "badcfe", ("b", "d", "f")),  # three swapped pairs: the earlier of each stays
    ],
)
def test_moved_is_the_fewest_kept_entries_that_changed_place(old, new, moved):
    first = go(old)
    assert go(new, first.state).moved == moved


def test_a_tie_is_broken_by_keeping_the_entries_that_were_earlier():
    """Several longest runs: the one that ends at the smallest old place stays, the rest move."""
    for old, new, moved in (
        ("ab", "ba", ("b",)),  # `a` was first, so `a` stays and `b` moves
        ("abcd", "cdab", ("c", "d")),  # `a b` and `c d` are both runs of two: `a b` stays
        ("abc", "bca", ("a",)),  # a run of two is longer than any run of one
    ):
        assert go(new, go(old).state).moved == moved, (old, new)


def longest_run(places):
    """An independent oracle: the length of the longest increasing run, by plain dynamic work."""
    best = [1] * len(places)
    for i in range(len(places)):
        for j in range(i):
            if places[j] < places[i]:
                best[i] = max(best[i], best[j] + 1)
    return max(best, default=0)


def earliest_end(places):
    """An independent oracle: the smallest last place over all the longest increasing runs."""
    length, best = [1] * len(places), []
    for i in range(len(places)):
        for j in range(i):
            if places[j] < places[i]:
                length[i] = max(length[i], length[j] + 1)
    top = max(length, default=0)
    best = [places[i] for i in range(len(places)) if length[i] == top]
    return min(best)


def test_moved_is_the_fewest_and_the_rest_keep_their_order_for_random_lists():
    rng = random.Random(2026)
    for _ in range(300):
        old = rng.sample(range(30), rng.randint(0, 25))
        new = rng.sample(range(40), rng.randint(0, 25))
        first = go(old)
        result = go(new, first.state)
        kept = [k for k in new if k in old]
        steady = [k for k in kept if k not in result.moved]
        assert len(kept) - len(result.moved) == longest_run([old.index(k) for k in kept])
        if steady:  # of all the longest runs, this one ends at the earliest old place
            assert max(old.index(k) for k in steady) == earliest_end([old.index(k) for k in kept])
        assert [old.index(k) for k in steady] == sorted(old.index(k) for k in steady)
        assert list(result.moved) == [k for k in kept if k in result.moved]  # in the new order
        assert result.removed == tuple(k for k in old if k not in new)
        assert [e.status for e in result.entries] == ["kept" if k in old else "new" for k in new]


def test_the_same_input_gives_the_same_moved_every_time():
    first = go("abcdef")
    answers = {go("fedcba", first.state).moved for _ in range(5)}
    assert len(answers) == 1


# -- the state ------------------------------------------------------------------------------------


def test_the_state_is_an_immutable_value_that_is_not_changed_by_reconciling():
    first = go("ab")
    before = (first.state.keys, repr(first.state))
    go("xyz", first.state)
    assert (first.state.keys, repr(first.state)) == before
    with pytest.raises(AttributeError):
        first.state.keys = ()
    with pytest.raises(AttributeError):
        first.state._next = 99
    with pytest.raises(AttributeError):
        del first.state._keys


def test_a_failed_call_leaves_the_state_usable_and_the_numbers_unspent():
    first = go("ab")
    with pytest.raises(TelEvaluationError):
        go(["a", "b", 1.5], first.state)  # a bad key
    again = go("abc", first.state)
    assert names(again) == ["W_0001", "W_0002", "W_0003"]


def test_a_state_is_required_and_must_be_a_repeater_state():
    r = rep()
    for bad in (None, {}, (), "x", object()):
        with pytest.raises(TypeError, match="RepeaterState"):
            r.reconcile(scope(xs=[1]), bad)
        with pytest.raises(TypeError, match="RepeaterState"):
            r.reconcile_tracked(scope(xs=[1]), bad)
    with pytest.raises(TypeError):
        r.reconcile(scope(xs=[1]))


def test_a_state_from_a_repeater_with_another_name_is_refused():
    first = go("ab", repeater=rep(name="Old"))
    for call in (rep(name="New").reconcile, rep(name="New").reconcile_tracked):
        with pytest.raises(ValueError, match="'Old'.*'New'"):
            call(scope(xs=["a", "b"]), first.state)
    assert names(go("ab", first.state, repeater=rep(name="Old"))) == ["Old_0001", "Old_0002"]


def test_the_empty_state_fits_any_repeater_and_a_state_keeps_working_after_an_error():
    assert names(go("a", repeater=rep(name="One"))) == ["One_0001"]
    assert names(go("a", repeater=rep(name="Two"))) == ["Two_0001"]
    first = go("ab", repeater=rep(name="One"))
    with pytest.raises(ValueError):
        go("ab", first.state, repeater=rep(name="Two"))
    assert names(go("abc", first.state, repeater=rep(name="One"))) == [
        "One_0001",
        "One_0002",
        "One_0003",
    ]


def test_the_empty_state_of_an_empty_list_is_still_the_empty_state_of_that_repeater():
    first = go([], repeater=rep(name="One"))
    with pytest.raises(ValueError):
        go("a", first.state, repeater=rep(name="Two"))


def test_keys_that_are_tuples_work_as_keys_in_the_state():
    r = rep("i, w in enumerate(xs)", "(w, i % 2)")
    first = r.reconcile(scope(xs="aabb"), RepeaterState())
    assert first.state.keys == (("a", 0), ("a", 1), ("b", 0), ("b", 1))
    second = r.reconcile(scope(xs="bbaa"), first.state)
    assert [(e.name, e.status) for e in second.entries] == [
        ("W_0003", "kept"),
        ("W_0004", "kept"),
        ("W_0001", "kept"),
        ("W_0002", "kept"),
    ]
    assert len(second.moved) == 2


def test_the_errors_of_the_list_are_raised_as_they_are():
    with pytest.raises(TelEvaluationError) as raised:
        rep().reconcile(scope(xs=["a", "a"]), RepeaterState())
    assert raised.value.code == "duplicate-key"


def test_the_list_and_the_keys_share_one_budget_in_a_reconcile_too():
    r = rep("w in xs", "(w, sum(range(10)))", limits=Limits(max_steps=100))
    assert len(r.reconcile(scope(xs=list(range(5))), RepeaterState()).entries) == 5
    with pytest.raises(TelLimitError) as raised:
        r.reconcile(scope(xs=list(range(20))), RepeaterState())
    assert raised.value.code == "limit-steps"


# -- entries --------------------------------------------------------------------------------------


def test_an_entry_gives_the_scope_for_its_children():
    r = rep("w in xs", "w['id']")
    result = r.reconcile(scope(xs=[{"id": 1, "t": "one"}, {"id": 2, "t": "two"}]), RepeaterState())
    child = tel.compile_expression("w['t'] + suffix", language="0.1")
    assert [child.evaluate(e.scope(scope(suffix="!"))) for e in result.entries] == ["one!", "two!"]


def test_an_entry_a_result_and_a_state_are_immutable_and_not_picklable():
    result = go("a")
    (entry,) = result.entries
    for obj in (entry, result, result.state):
        with pytest.raises(AttributeError):
            obj.zzz = 1
        with pytest.raises(TypeError):
            pickle.dumps(obj)
        assert copy.copy(obj) is obj and copy.deepcopy(obj) is obj
    with pytest.raises(AttributeError):
        entry.name = "x"
    with pytest.raises(AttributeError):
        result.moved = ()
    with pytest.raises(AttributeError):
        del result.entries
    assert repr(entry) == "Entry('W_0001', index=0, key='a', new)"
    assert "1 entries" in repr(result) and "1 keys" in repr(result.state)


# -- tracked --------------------------------------------------------------------------------------


def test_a_tracked_reconcile_reports_what_the_list_and_the_keys_read():
    r = rep("w in box.rows", "w.id + off")
    box = type("B", (), {"rows": [type("R", (), {"id": 1})(), type("R", (), {"id": 2})()]})()
    result = r.reconcile_tracked(scope(box=box, off=10), RepeaterState())
    assert isinstance(result, Tracked) and isinstance(result.value, Reconciliation)
    assert result.reads == {"box.rows", "w.id", "off"}
    assert [e.key for e in result.value.entries] == [11, 12]


def test_a_bare_loop_variable_in_the_key_is_reported_as_written_too():
    result = rep().reconcile_tracked(scope(xs=["a"]), RepeaterState())
    assert result.reads == {"xs", "w"}


def test_a_tracked_reconcile_gives_the_same_result_as_a_plain_one():
    first = go("abc")
    plain = go("bcd", first.state)
    tracked = rep().reconcile_tracked(scope(xs=list("bcd")), first.state).value
    assert [(e.key, e.name, e.status) for e in tracked.entries] == [
        (e.key, e.name, e.status) for e in plain.entries
    ]
    assert (tracked.moved, tracked.removed, tracked.state.keys) == (
        plain.moved,
        plain.removed,
        plain.state.keys,
    )


def test_an_error_in_a_tracked_reconcile_carries_the_paths_read_so_far():
    r = rep("w in box.rows", "w.id + off")
    with pytest.raises(tel.TelError) as raised:
        r.reconcile_tracked(scope(xs=[]), RepeaterState())
    assert raised.value.code == "unknown-name" and raised.value.reads == {"box"}


def test_a_failed_tracked_reconcile_after_some_keys_reports_all_the_reads():
    r = rep("w in xs", "w.id + off")
    with pytest.raises(tel.TelError) as raised:
        r.reconcile_tracked(scope(xs=[{"id": 1}, {"id": 2}]), RepeaterState())
    assert raised.value.code == "unknown-name"
    assert raised.value.reads == {"xs", "w.id", "off"}
