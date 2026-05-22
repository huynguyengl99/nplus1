"""SQLAlchemy integration for N+1 detection.

Monkey-patches SQLAlchemy internals to emit signals on lazy loads,
eager loads, and attribute access.
"""

import inspect
from typing import Any, Self

from sqlalchemy.orm import attributes, loading, query, strategies

from nplusone.core import signals


def to_key(instance: Any) -> str:
    """Create a unique key for a SQLAlchemy model instance."""
    model = type(instance)
    return ":".join(
        [model.__name__]
        + [format(instance.__dict__.get(key.key)) for key in get_primary_keys(model)]
    )


def get_primary_keys(model: type) -> list[Any]:
    """Extract primary key properties from a SQLAlchemy model."""
    mapper = model.__mapper__  # type: ignore[attr-defined]
    return [mapper.get_property_by_column(column) for column in mapper.primary_key]


def parse_load(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
    ret: Any,
) -> list[str]:
    """Extract loaded instance keys from query results."""
    return [to_key(row) for row in ret if hasattr(row, "__table__")]


def parse_lazy_load(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> tuple[type, str, str]:
    """Extract model, instance key, and field from a lazy load."""
    loader, state, _ = args  # type: ignore[misc]
    return state.object.__class__, to_key(state.object), loader.parent_property.key


def parse_attribute_get(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> tuple[type, str, list[str]] | None:
    """Extract attribute access context from InstrumentedAttribute.__get__."""
    attr, instance = args[:2]  # type: ignore[index]
    if instance is None:
        return None
    return attr.class_, attr.key, [to_key(instance)]


# Emit `lazy_load` on lazy loader execution
strategies.LazyLoader._load_for_state = signals.signalify(  # type: ignore[attr-defined]
    signals.lazy_load,
    strategies.LazyLoader._load_for_state,  # type: ignore[attr-defined]
    parser=parse_lazy_load,
)


def parse_populate(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> tuple[type, str, list[str], int]:
    """Extract eager load context from populate functions."""
    query_context = args[0]  # type: ignore[index]
    state = args[2]  # type: ignore[index]
    instance = state.object
    return (
        instance.__class__,
        context["key"],  # type: ignore[index]
        [to_key(instance)],
        id(query_context),
    )


# Emit `eager_load` on populating from `joinedload` or `subqueryload`
_original_populate_full = loading._populate_full  # type: ignore[attr-defined]


def _populate_full(*args: Any, **kwargs: Any) -> Any:
    """Wrapper that emits eager_load signals after populating."""
    ret = _original_populate_full(*args, **kwargs)
    # Extract populators from function arguments
    # Signature: _populate_full(context, row, state, ..., populators, ...)
    # Use positional inspection to get the populators dict
    sig = inspect.signature(_original_populate_full)
    bound = sig.bind(*args, **kwargs)
    bound.apply_defaults()
    context_dict = bound.arguments
    for key, _ in context_dict.get("populators", {}).get("eager", []):
        if context_dict.get("dict_", {}).get(key):
            signals.eager_load.send(
                signals.get_worker(),
                args=args,
                kwargs=kwargs,
                context={"key": key},
                parser=parse_populate,
            )
    return ret


loading._populate_full = _populate_full  # type: ignore[attr-defined]


# Emit `touch` on attribute access
attributes.InstrumentedAttribute.__get__ = signals.signalify(  # type: ignore[method-assign]
    signals.touch,
    attributes.InstrumentedAttribute.__get__,
    parser=parse_attribute_get,
)


def _clause_value(clause: Any) -> int | None:
    """Extract integer value from a SQLAlchemy limit/offset clause."""
    if clause is None:
        return None
    if isinstance(clause, int):
        return clause
    return getattr(clause, "value", None)


def is_single(offset: Any, limit: Any) -> bool:
    """Check if a query is limited to a single result."""
    limit_val = _clause_value(limit)
    offset_val = _clause_value(offset) or 0
    return limit_val is not None and limit_val - offset_val == 1


# Emit `load` or `ignore_load` on query execution.
# In SQLAlchemy 2.0, Query.all() calls _iter() instead of __iter__.
_original_query_iter = query.Query._iter  # type: ignore[attr-defined]


def _query_iter(self: Any) -> Any:
    """Wrapper that emits load/ignore_load signals on query execution."""
    result = _original_query_iter(self)

    # Collect rows to determine what was loaded
    rows = result.all()
    signal = (
        signals.ignore_load
        if is_single(self._offset_clause, self._limit_clause)
        else signals.load
    )
    signal.send(
        signals.get_worker(),
        args=(self,),
        ret=rows,
        parser=parse_load,
    )

    # Return a fake result that yields the already-consumed rows
    return _RowListResult(list(rows))


class _RowListResult:
    """Wrapper that presents pre-fetched rows as a result-like object."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        """Return all rows."""
        return self._rows

    def __iter__(self) -> Any:
        """Iterate over rows."""
        return iter(self._rows)

    def first(self) -> Any:
        """Return first row or None."""
        return self._rows[0] if self._rows else None

    def one(self) -> Any:
        """Return exactly one row."""
        if len(self._rows) != 1:
            msg = f"Expected 1 row, got {len(self._rows)}"
            raise Exception(msg)  # noqa: TRY002
        return self._rows[0]

    def one_or_none(self) -> Any:
        """Return one row or None."""
        if len(self._rows) > 1:
            msg = f"Expected 0 or 1 rows, got {len(self._rows)}"
            raise Exception(msg)  # noqa: TRY002
        return self._rows[0] if self._rows else None

    def unique(self) -> Self:
        """Return self (already unique)."""
        return self

    def scalars(self) -> Self:
        """Return self (already scalar)."""
        return self


query.Query._iter = _query_iter  # type: ignore[attr-defined]


def parse_get(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
    ret: Any,
) -> list[str]:
    """Extract instance key from a single-object query result."""
    return [to_key(ret)] if hasattr(ret, "__table__") else []


# Ignore records loaded during `one` and `one_or_none`
for _method_name in ["one_or_none", "one"]:
    if hasattr(query.Query, _method_name):
        _original = getattr(query.Query, _method_name)
        _decorated = signals.signalify(signals.ignore_load, _original, parse_get)
        setattr(query.Query, _method_name, _decorated)
