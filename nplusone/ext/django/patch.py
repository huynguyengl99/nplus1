"""Monkey patches for Django's ORM to emit detection signals.

Applied at import time when nplusone.ext.django is imported.
Targets Django 4.2+.
"""

import copy
import functools
import importlib
import inspect
import threading
from typing import Any

from django.conf import settings
from django.db.models import Model, query
from django.db.models.fields.related_descriptors import (
    ForwardManyToOneDescriptor,
    ReverseOneToOneDescriptor,
    create_forward_many_to_many_manager,
    create_reverse_many_to_one_manager,
)

from nplusone.core import signals


def get_worker() -> str:
    """Get thread ID as the worker identifier for Django."""
    return str(threading.current_thread().ident)


def setup_state() -> None:
    """Configure signals to use thread-scoped workers."""
    signals.get_worker = get_worker


setup_state()


def to_key(instance: Any) -> str:
    """Create a unique key for a Django model instance."""
    model = type(instance)
    return ":".join([model.__name__, format(instance.pk)])


def _patch_module(original: Any, patched: Any) -> None:
    """Replace a function in its original module."""
    module = importlib.import_module(original.__module__)
    setattr(module, original.__name__, patched)


def signalify_queryset(
    func: Any,
    parser: Any = None,
    **context: Any,
) -> Any:
    """Wrap a queryset-returning function to emit lazy_load on fetch."""

    @functools.wraps(func)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        queryset = func(*args, **kwargs)
        ctx = copy.copy(context)
        ctx["args"] = context.get("args", args)
        ctx["kwargs"] = context.get("kwargs", kwargs)
        queryset._clone = signalify_queryset(queryset._clone, parser=parser, **ctx)
        queryset._fetch_all = _signalify_fetch_all(queryset, parser=parser, **ctx)
        queryset._context = ctx
        return queryset

    return wrapped


def _signalify_fetch_all(
    queryset: Any,
    parser: Any = None,
    **context: Any,
) -> Any:
    """Signal lazy load when QuerySet._fetch_all fetches rows."""
    func = queryset._fetch_all

    @functools.wraps(func)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if queryset._result_cache is None:
            signals.lazy_load.send(
                get_worker(),
                args=args,
                kwargs=kwargs,
                ret=None,
                context=context,
                parser=parser,
            )
        return func(*args, **kwargs)

    return wrapped


def get_related_name(model: type) -> str:
    """Get the default reverse relation name for a model."""
    return f"{model._meta.model_name}_set"  # type: ignore[attr-defined]


def parse_field(field: Any) -> tuple[type, str]:
    """Extract related model and field name from a Django field."""
    return (
        field.related_model,
        field.remote_field.name or get_related_name(field.related_model),
    )


def parse_reverse_field(field: Any) -> tuple[type, str]:
    """Extract model and field name from a reverse field."""
    return field.model, field.name


def parse_related(context: dict[str, Any]) -> tuple[type, str]:
    """Extract model and related name from manager context."""
    rel = context["rel"]
    return _parse_related_parts(rel.model, rel.related_name, rel.related_model)


def _parse_related_parts(
    model: type,
    related_name: str | None,
    related_model: type,
) -> tuple[type, str]:
    """Build (model, field_name) from relation parts."""
    return (
        model,
        related_name or get_related_name(related_model),
    )


def parse_reverse_one_to_one_queryset(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any],
) -> tuple[type, str, str]:
    """Parse reverse OneToOne queryset creation."""
    descriptor = context["args"][0]
    field = descriptor.related.field
    model, name = parse_field(field)
    instance = context["kwargs"]["instance"]
    return model, to_key(instance), name


def parse_forward_many_to_one_queryset(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any],
) -> tuple[type, str, str]:
    """Parse forward ManyToOne queryset creation."""
    descriptor = context["args"][0]
    instance = context["kwargs"]["instance"]
    return descriptor.field.model, to_key(instance), descriptor.field.name


def parse_many_related_queryset(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any],
) -> tuple[type, str, str]:
    """Parse ManyToMany queryset creation."""
    rel = context["rel"]
    manager = context["args"][0]
    model = manager.instance.__class__
    related_model = manager.target_field.related_model
    field = manager.prefetch_cache_name if rel.related_name else None
    return (
        model,
        to_key(manager.instance),
        field or get_related_name(related_model),
    )


def parse_foreign_related_queryset(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any],
) -> tuple[type, str, str]:
    """Parse reverse ForeignKey queryset creation."""
    model, name = parse_related(context)
    descriptor = context["args"][0]
    return model, to_key(descriptor.instance), name


# Suppress lazy_load signals during prefetch_related execution
query.prefetch_one_level = signals.designalify(
    signals.lazy_load,
    query.prefetch_one_level,
)


def parse_get(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
    ret: Any,
) -> list[str]:
    """Extract instance key from QuerySet.get() result."""
    return [to_key(ret)] if isinstance(ret, Model) else []


# Ignore records loaded during `get`
query.QuerySet.get = signals.signalify(  # type: ignore[method-assign]
    signals.ignore_load,
    query.QuerySet.get,
    parser=parse_get,
)


# Signalify descriptor queryset methods for lazy load detection
ReverseOneToOneDescriptor.get_queryset = signalify_queryset(  # type: ignore[method-assign]
    ReverseOneToOneDescriptor.get_queryset,
    parser=parse_reverse_one_to_one_queryset,
)
ForwardManyToOneDescriptor.get_queryset = signalify_queryset(  # type: ignore[method-assign]
    ForwardManyToOneDescriptor.get_queryset,
    parser=parse_forward_many_to_one_queryset,
)

# Cache signatures for manager creation functions
_m2m_sig = inspect.signature(create_forward_many_to_many_manager)
_rev_m2o_sig = inspect.signature(create_reverse_many_to_one_manager)


def _create_forward_many_to_many_manager(*args: Any, **kwargs: Any) -> Any:
    """Patched manager factory that tracks ManyToMany lazy loads."""
    bound = _m2m_sig.bind(*args, **kwargs)
    bound.apply_defaults()
    context = dict(bound.arguments)
    manager = create_forward_many_to_many_manager(*args, **kwargs)
    manager.get_queryset = signalify_queryset(  # type: ignore[method-assign]
        manager.get_queryset,
        parser=parse_many_related_queryset,
        **context,
    )
    return manager


_patch_module(create_forward_many_to_many_manager, _create_forward_many_to_many_manager)


def _create_reverse_many_to_one_manager(*args: Any, **kwargs: Any) -> Any:
    """Patched manager factory that tracks reverse FK lazy loads."""
    bound = _rev_m2o_sig.bind(*args, **kwargs)
    bound.apply_defaults()
    context = dict(bound.arguments)
    manager = create_reverse_many_to_one_manager(*args, **kwargs)
    manager.get_queryset = signalify_queryset(  # type: ignore[method-assign]
        manager.get_queryset,
        parser=parse_foreign_related_queryset,
        **context,
    )
    return manager


_patch_module(create_reverse_many_to_one_manager, _create_reverse_many_to_one_manager)


def parse_forward_many_to_one_get(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> tuple[type, str, list[str]] | None:
    """Parse forward ManyToOne descriptor __get__ for touch signals."""
    descriptor, instance, _ = args  # type: ignore[misc]
    if instance is None:
        return None
    field, model = parse_reverse_field(descriptor.field)
    return field, model, [to_key(instance)]


# Emit `touch` on FK descriptor access
ForwardManyToOneDescriptor.__get__ = signals.signalify(  # type: ignore[method-assign]
    signals.touch,
    ForwardManyToOneDescriptor.__get__,
    parser=parse_forward_many_to_one_get,
)


def parse_reverse_one_to_one_get(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> tuple[type, str, list[str]] | None:
    """Parse reverse OneToOne descriptor __get__ for touch signals."""
    descriptor, instance = args[:2]  # type: ignore[index]
    if instance is None:
        return None
    model, field = parse_field(descriptor.related.field)
    return model, field, [to_key(instance)]


# Emit `touch` on reverse OneToOne descriptor access
ReverseOneToOneDescriptor.__get__ = signals.signalify(  # type: ignore[method-assign]
    signals.touch,
    ReverseOneToOneDescriptor.__get__,
    parser=parse_reverse_one_to_one_get,
)


def parse_fetch_all(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> tuple[type, str, list[str]] | None:
    """Parse fetch_all for touch signals on prefetched querysets."""
    self = args[0]  # type: ignore[index]
    if hasattr(self, "_context"):
        manager = self._context["args"][0]
        instance = manager.instance
        if manager.__class__.__name__ == "ManyRelatedManager":
            return (
                instance.__class__,
                _parse_manager_field(manager, self._context["rel"]),
                [to_key(instance)],
            )
        else:
            model, field = parse_related(self._context)
            return model, field, [to_key(instance)]
    return None


def _parse_manager_field(manager: Any, rel: Any) -> str:
    """Extract field name from a relation manager."""
    if manager.reverse:
        return rel.related_name or get_related_name(rel.related_model)
    return rel.field.name or get_related_name(rel.model)


def parse_load(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
    ret: Any,
) -> list[str]:
    """Extract loaded instance keys from queryset results."""
    return [to_key(row) for row in ret if isinstance(row, Model)]


def is_single(low: int, high: int | None) -> bool:
    """Check if a query is limited to a single result."""
    return high is not None and high - low == 1


# On queryset fetch, emit `touch` if results have been prefetched; emit `load`
# if the query requests more than one record, else `ignore_load`.
_original_fetch_all = query.QuerySet._fetch_all


def _fetch_all(self: Any) -> None:
    """Patched _fetch_all that emits load signals."""
    if self._prefetch_done:
        signals.touch.send(
            get_worker(),
            args=(self,),
            parser=parse_fetch_all,
        )
    _original_fetch_all(self)
    signal = (
        signals.ignore_load
        if is_single(self.query.low_mark, self.query.high_mark)
        else signals.load
    )
    signal.send(
        get_worker(),
        args=(self,),
        ret=self._result_cache,
        parser=parse_load,
    )


query.QuerySet._fetch_all = _fetch_all  # type: ignore[method-assign]


# Store init args on RelatedPopulator for later use in parse_eager_select
_original_related_populator_init = query.RelatedPopulator.__init__


def _related_populator_init(self: Any, *args: Any, **kwargs: Any) -> None:
    """Patched __init__ that stores args for eager load detection."""
    _original_related_populator_init(self, *args, **kwargs)
    self.__nplusone__ = {
        "args": args,
        "kwargs": kwargs,
    }


query.RelatedPopulator.__init__ = _related_populator_init  # type: ignore[method-assign]


def parse_eager_select(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> tuple[type, str, list[str], int]:
    """Parse eager load context from select_related populator."""
    populator = args[0]  # type: ignore[index]
    instance = args[2]  # type: ignore[index]
    meta = populator.__nplusone__
    klass_info, select, *_rest = meta["args"]
    field = klass_info["field"]
    # Use issubclass to handle MTI: if the field is defined on a parent model,
    # the instance's model is a subclass of field.model (forward FK).
    # If the field is on an unrelated model, it's a reverse OneToOne.
    model, name = (
        parse_field(field)
        if not issubclass(type(instance), field.model)
        else parse_reverse_field(field)
    )
    return model, name, [to_key(instance)], id(select)


# Emit `eager_load` on populating from `select_related`.
# Skip nullable FK fields entirely — select_related on a nullable FK is always
# a valid optimization (the LEFT JOIN prevents N+1 on rows where the FK IS
# populated, and the overhead for NULL rows is negligible).
_original_populate = query.RelatedPopulator.populate


def _related_populator_populate(self: Any, *args: Any, **kwargs: Any) -> Any:
    """Patched populate that emits eager_load, skipping nullable FKs."""
    ret = _original_populate(self, *args, **kwargs)
    # Skip nullable FK fields — select_related is always valid for them
    field = self.__nplusone__["args"][0]["field"]
    if getattr(field, "null", False):
        return ret
    signals.eager_load.send(
        signals.get_worker(),
        args=(self,) + tuple(args),
        kwargs=kwargs,
        context={},
        parser=parse_eager_select,
    )
    return ret


query.RelatedPopulator.populate = _related_populator_populate  # type: ignore[method-assign]


def parse_eager_join(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> tuple[type, str, list[str], int]:
    """Parse eager load context from prefetch_related."""
    instances, descriptor, fetcher, level = args  # type: ignore[misc]
    model = instances[0].__class__
    field, _ = fetcher.get_current_to_attr(level)
    keys = [to_key(instance) for instance in instances]
    return model, field, keys, id(instances)


# Emit `eager_load` on populating from `prefetch_related`.
# Uses a custom wrapper instead of signalify to support NPLUSONE_SKIP_EMPTY_PREFETCH:
# when enabled, skip the signal if the prefetch returned zero related objects.
_prefetch_one_level_inner = query.prefetch_one_level  # already designalify'd


def _prefetch_one_level_eager(*args: Any, **kwargs: Any) -> Any:
    """Wrapper that emits eager_load, optionally skipping empty prefetches."""
    ret = _prefetch_one_level_inner(*args, **kwargs)
    # ret is (all_related_objects, additional_lookups)
    all_related = ret[0] if isinstance(ret, tuple) else []
    if not all_related and _should_skip_empty_prefetch():
        return ret
    signals.eager_load.send(
        signals.get_worker(),
        args=args,
        kwargs=kwargs,
        ret=ret,
        context={},
        parser=parse_eager_join,
    )
    return ret


def _should_skip_empty_prefetch() -> bool:
    """Check if NPLUSONE_SKIP_EMPTY_PREFETCH is enabled in Django settings."""
    try:
        return bool(getattr(settings, "NPLUSONE_SKIP_EMPTY_PREFETCH", False))
    except Exception:
        return False


query.prefetch_one_level = _prefetch_one_level_eager


# Emit `touch` on indexing into prefetched QuerySet instances
_original_getitem_queryset = query.QuerySet.__getitem__


def _getitem_queryset(self: Any, index: Any) -> Any:
    """Patched __getitem__ that emits touch for prefetched querysets."""
    if self._prefetch_done:
        signals.touch.send(
            get_worker(),
            args=(self,),
            parser=parse_fetch_all,
        )
    return _original_getitem_queryset(self, index)


query.QuerySet.__getitem__ = _getitem_queryset  # type: ignore[method-assign]
