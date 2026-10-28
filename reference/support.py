"""Objects the reference cases put in a scope. Ported from Tesserae's `tests/test_expr.py`."""

from typing import Any


class Plain:
    """An ordinary object: public attributes are readable, a method is not, `_x` is private."""

    def __init__(self) -> None:
        self.title = "t"
        self.items = [1, 2]
        self._secret = "no"

    def method(self) -> int:
        return 1


class Trap:
    """Anything that gets past a sandbox and calls, mutates, iterates or searches this sets
    `tripped`. A refused expression leaves `tripped` empty."""

    tripped: list[Any] = []

    def __init__(self, name: str = "trap") -> None:
        self._name = name

    def __getattr__(self, name: str) -> Trap:
        if name.startswith("_"):
            raise AttributeError(name)
        return Trap(name)

    def __call__(self, *a: Any, **k: Any) -> int:
        Trap.tripped.append(("called", self._name))
        return 1

    def __setattr__(self, name: str, value: Any) -> None:
        if name != "_name":
            Trap.tripped.append(("set", name))
        object.__setattr__(self, name, value)

    def __iter__(self) -> Any:
        Trap.tripped.append(("iterated", self._name))
        return iter(())

    def __getitem__(self, key: Any) -> Trap:
        return Trap(f"item {key}")

    def __len__(self) -> int:
        Trap.tripped.append(("len", self._name))
        return 1

    def __contains__(self, item: Any) -> bool:
        Trap.tripped.append(("contains", self._name))
        return True

    def dangerous(self) -> None:
        Trap.tripped.append(("method", self._name))


def _install_traps() -> None:
    """Make every special method an operator, comparison, index, hash or format could call record
    the call, so a missing check is seen as an actual call and not only as a different error."""
    results: dict[str, Any] = {
        "__eq__": True, "__ne__": True, "__lt__": True, "__le__": True, "__gt__": True,
        "__ge__": True, "__bool__": True, "__index__": 0, "__int__": 0, "__float__": 0.0,
        "__hash__": 1, "__format__": "x",
    }  # fmt: skip
    for name in (
        "__add__ __radd__ __sub__ __rsub__ __mul__ __rmul__ __truediv__ __rtruediv__ "
        "__floordiv__ __rfloordiv__ __mod__ __rmod__ __pow__ __rpow__ __neg__ __pos__ __abs__"
    ).split():
        results[name] = 1

    def make(special: str, result: Any) -> Any:
        def method(self: Trap, *args: Any, **kwargs: Any) -> Any:
            Trap.tripped.append(("special", special))
            return result

        return method

    for special, result in results.items():
        setattr(Trap, special, make(special, result))


_install_traps()
