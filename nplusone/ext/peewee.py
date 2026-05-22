"""Peewee integration for N+1 detection.

Patches are applied lazily via ``apply_patches()`` — only when explicitly
called. Auto-applied on import for backward compatibility.
"""

from typing import Any

from peewee import (
    BackrefAccessor,
    BaseModelSelect,
    BaseQuery,
    ForeignKeyAccessor,
    ManyToManyQuery,
    SelectQuery,
    database_required,
)

from nplusone.core import signals

_patched = False


def parse_get_object(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> tuple[type, str, str]:
    """Extract FK lazy load context."""
    accessor, instance = args
    return accessor.field.model, to_key(instance), accessor.field.name


def parse_reverse_get(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> tuple[type, str, str]:
    """Extract reverse relationship lazy load context."""
    accessor, instance = args
    return accessor.field.rel_model, to_key(instance), accessor.field.backref


def to_key(instance: Any) -> str:
    """Create a unique key for a Peewee model instance."""
    model = type(instance)
    return ":".join([model.__name__, format(instance.get_id())])


def parse_load(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
    ret: Any,
) -> list[str]:
    """Extract loaded instance keys from query results."""
    return [to_key(row) for row in ret]


def is_single(offset: int | None, limit: int | None) -> bool:
    """Check if a query is limited to a single result."""
    return limit is not None and limit - (offset or 0) == 1


def apply_patches() -> None:
    """Apply monkey patches to Peewee's ORM.

    Safe to call multiple times (idempotent).
    """
    global _patched  # noqa: PLW0603
    if _patched:
        return
    _patched = True

    # --- FK accessor patches ---

    def get_rel_instance(self: Any, instance: Any) -> Any:
        """Custom FK accessor that emits lazy_load signals."""
        value = instance.__data__.get(self.name)
        if value is not None or self.name in instance.__rel__:
            if self.name not in instance.__rel__:
                signals.lazy_load.send(
                    signals.get_worker(),
                    args=(self, instance),
                    parser=parse_get_object,
                )
                obj = self.rel_model.get(self.field.rel_field == value)
                instance.__rel__[self.name] = obj
            return instance.__rel__[self.name]
        elif not self.field.null:
            raise self.rel_model.DoesNotExist
        return value

    ForeignKeyAccessor.get_rel_instance = get_rel_instance

    def backref_get(
        self: Any,
        instance: Any,
        instance_type: type | None = None,
    ) -> Any:
        """Custom backref accessor that marks queries for lazy_load detection."""
        if instance is not None:
            dest = self.field.rel_field.name
            backref_query = self.rel_model.select().where(
                self.field == getattr(instance, dest)
            )
            backref_query._context = {
                "args": (self, instance),
                "kwargs": {"instance_type": instance_type},
            }
            return backref_query
        return self

    BackrefAccessor.__get__ = backref_get

    # --- Query iteration patches ---

    original_model_select_iter = BaseModelSelect.__iter__

    def _model_select_iter(self: Any) -> Any:
        """Wrapper that emits lazy_load for ManyToMany queries."""
        if isinstance(self, ManyToManyQuery):
            signals.lazy_load.send(
                signals.get_worker(),
                args=(self._accessor, self._instance),
                parser=parse_get_object,
            )
        return original_model_select_iter(self)

    BaseModelSelect.__iter__ = _model_select_iter

    # --- Query execution patches ---

    original_query_execute = BaseQuery.execute

    def _query_execute(self: Any, database: Any) -> Any:
        """Wrapper that emits load/ignore_load and lazy_load signals."""
        ret = original_query_execute(self, database)
        if hasattr(self, "_context"):
            signals.lazy_load.send(
                signals.get_worker(),
                args=self._context["args"],
                kwargs=self._context["kwargs"],
                parser=parse_reverse_get,
            )
        if not isinstance(self, SelectQuery):
            return ret
        signal = (
            signals.ignore_load
            if is_single(self._offset, self._limit)
            else signals.load
        )
        signal.send(
            signals.get_worker(),
            args=(self,),
            ret=list(ret),
            parser=parse_load,
        )
        return ret

    BaseQuery.execute = database_required(_query_execute)


# Auto-apply on import (backward compat with `import nplusone.ext.peewee`)
apply_patches()
