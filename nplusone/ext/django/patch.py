"""Monkey patches for Django's ORM to emit detection signals.

Patches are applied lazily via ``apply_patches()`` — only when
``NPLUSONE_ENABLED`` is True (or unset). If ``NPLUSONE_ENABLED = False``
in Django settings, no patching occurs and there is zero runtime overhead.
"""

import contextvars
import copy
import functools
import importlib
import inspect
import threading
from typing import Any

from django.conf import settings
from django.contrib.contenttypes.fields import create_generic_related_manager
from django.db.models import Model, query
from django.db.models.fields.related_descriptors import (
    ForwardManyToOneDescriptor,
    ManyToManyDescriptor,
    ReverseOneToOneDescriptor,
    create_forward_many_to_many_manager,
    create_reverse_many_to_one_manager,
)

from nplusone.core import signals

_patched = False


nplus1_context: contextvars.ContextVar[str] = contextvars.ContextVar("nplus1_worker")


def get_worker() -> str:
    """Get the current worker identifier for Django.

    Uses a contextvars-based ID when set (ASGI-safe), falling back to
    thread ID for WSGI compatibility.
    """
    try:
        return nplus1_context.get()
    except LookupError:
        return str(threading.current_thread().ident)


def setup_state() -> None:
    """Configure signals to use thread-scoped workers."""
    signals.get_worker = get_worker


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
        if not isinstance(queryset, query.QuerySet):
            return queryset  # prefetch cache may return a list
        ctx = copy.copy(context)
        ctx["args"] = context.get("args", args)
        ctx["kwargs"] = context.get("kwargs", kwargs)
        queryset._clone = signalify_queryset(queryset._clone, parser=parser, **ctx)  # type: ignore[attr-defined]
        queryset._fetch_all = _signalify_fetch_all(queryset, parser=parser, **ctx)  # type: ignore[method-assign]
        queryset._context = ctx  # type: ignore[attr-defined]
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


def parse_generic_related_queryset(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any],
) -> tuple[type, str, str]:
    """Parse GenericRelation queryset creation."""
    manager = context["args"][0]
    instance = manager.instance
    return instance.__class__, to_key(instance), manager.prefetch_cache_name


def parse_get(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
    ret: Any,
) -> list[str]:
    """Extract instance key from QuerySet.get() result."""
    return [to_key(ret)] if isinstance(ret, Model) else []


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


def parse_many_to_many_descriptor_get(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> tuple[type, str, list[str]] | None:
    """Parse ManyToMany/ReverseManyToOne descriptor __get__ for touch signals.

    Only emits a touch when the instance has prefetched data for this field,
    ensuring we don't spuriously mark non-prefetched accesses.
    """
    descriptor, instance = args[:2]  # type: ignore[index]
    if instance is None:
        return None
    prefetch_cache = getattr(instance, "_prefetched_objects_cache", None)
    if not prefetch_cache:
        return None
    # Determine the prefetch cache name based on descriptor direction.
    # Forward M2M (e.g. User.hobbies): cache key = field.name
    # Reverse M2M (e.g. Hobby.users): cache key = field.related_query_name()
    if not hasattr(descriptor, "field"):
        return None
    if getattr(descriptor, "reverse", False):
        cache_name = descriptor.field.related_query_name()
    else:
        cache_name = descriptor.field.name
    # Only emit touch if prefetch cache is populated for this field
    if cache_name not in prefetch_cache:
        return None
    model = instance.__class__
    return model, cache_name, [to_key(instance)]


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
        elif manager.__class__.__name__ == "GenericRelatedObjectManager":
            return (
                instance.__class__,
                manager.prefetch_cache_name,
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


def parse_populate_load(
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    context: dict[str, Any] | None,
    ret: Any,
) -> list[str]:
    """Extract instance key from RelatedPopulator.populate for load signal.

    This adds select_related child instances to the LazyListener's loaded set,
    enabling N+1 detection on their FK fields. Without this, accessing
    ``pet.user.occupation`` (where user was loaded via select_related but
    occupation was not) would go undetected.
    """
    populator = args[0]  # type: ignore[index]
    from_obj = args[2]  # type: ignore[index]
    meta = populator.__nplusone__
    klass_info = meta["args"][0]
    field = klass_info["field"]
    try:
        related_obj = field.get_cached_value(from_obj)
    except KeyError:
        return []
    if related_obj is None:
        return []
    return [to_key(related_obj)]


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


def _should_skip_empty_prefetch() -> bool:
    """Check if NPLUSONE_SKIP_EMPTY_PREFETCH is enabled in Django settings."""
    try:
        return bool(getattr(settings, "NPLUSONE_SKIP_EMPTY_PREFETCH", False))
    except Exception:
        return False


def apply_patches() -> None:
    """Apply monkey patches to Django's ORM.

    Called once at import time by ``nplusone.ext.django.__init__``.
    Guarded by ``NPLUSONE_ENABLED`` setting — if False, no patches
    are applied and there is zero runtime overhead.

    Safe to call multiple times (idempotent).
    """
    global _patched  # noqa: PLW0603
    if _patched:
        return
    _patched = True

    setup_state()

    # Cache signatures for manager creation functions
    m2m_sig = inspect.signature(create_forward_many_to_many_manager)
    rev_m2o_sig = inspect.signature(create_reverse_many_to_one_manager)
    gen_rel_sig = inspect.signature(create_generic_related_manager)

    # --- Lazy load detection patches ---

    # Suppress lazy_load signals during prefetch_related execution
    query.prefetch_one_level = signals.designalify(
        signals.lazy_load,
        query.prefetch_one_level,
    )

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

    # Patch manager factories for M2M and reverse FK
    def _create_forward_many_to_many_manager(*args: Any, **kwargs: Any) -> Any:
        bound = m2m_sig.bind(*args, **kwargs)
        bound.apply_defaults()
        ctx = dict(bound.arguments)
        manager = create_forward_many_to_many_manager(*args, **kwargs)
        manager.get_queryset = signalify_queryset(  # type: ignore[method-assign]
            manager.get_queryset,
            parser=parse_many_related_queryset,
            **ctx,
        )
        return manager

    _patch_module(
        create_forward_many_to_many_manager,
        _create_forward_many_to_many_manager,
    )

    def _create_reverse_many_to_one_manager(*args: Any, **kwargs: Any) -> Any:
        bound = rev_m2o_sig.bind(*args, **kwargs)
        bound.apply_defaults()
        ctx = dict(bound.arguments)
        manager = create_reverse_many_to_one_manager(*args, **kwargs)
        manager.get_queryset = signalify_queryset(  # type: ignore[method-assign]
            manager.get_queryset,
            parser=parse_foreign_related_queryset,
            **ctx,
        )
        return manager

    _patch_module(
        create_reverse_many_to_one_manager,
        _create_reverse_many_to_one_manager,
    )

    def _create_generic_related_manager(*args: Any, **kwargs: Any) -> Any:
        bound = gen_rel_sig.bind(*args, **kwargs)
        bound.apply_defaults()
        ctx = dict(bound.arguments)
        manager = create_generic_related_manager(*args, **kwargs)
        manager.get_queryset = signalify_queryset(
            manager.get_queryset,
            parser=parse_generic_related_queryset,
            **ctx,
        )
        return manager

    _patch_module(
        create_generic_related_manager,
        _create_generic_related_manager,
    )

    # --- Touch signal patches (for eager load tracking) ---

    # Emit `touch` on FK descriptor access
    ForwardManyToOneDescriptor.__get__ = signals.signalify(  # type: ignore[method-assign]
        signals.touch,
        ForwardManyToOneDescriptor.__get__,
        parser=parse_forward_many_to_one_get,
    )

    # Emit `touch` on reverse OneToOne descriptor access
    ReverseOneToOneDescriptor.__get__ = signals.signalify(  # type: ignore[method-assign]
        signals.touch,
        ReverseOneToOneDescriptor.__get__,
        parser=parse_reverse_one_to_one_get,
    )

    # Emit `touch` on ManyToMany descriptor access (only when prefetch cache
    # is populated). This covers the case where the M2M manager class was
    # created before apply_patches() replaced the factory function, so its
    # get_queryset() is not wrapped by signalify_queryset.
    ManyToManyDescriptor.__get__ = signals.signalify(  # type: ignore[method-assign]
        signals.touch,
        ManyToManyDescriptor.__get__,
        parser=parse_many_to_many_descriptor_get,
    )

    # --- Load/ignore_load signal patches ---

    original_fetch_all = query.QuerySet._fetch_all

    def _fetch_all(self: Any) -> None:
        if self._prefetch_done:
            signals.touch.send(
                get_worker(),
                args=(self,),
                parser=parse_fetch_all,
            )
        original_fetch_all(self)
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

    # --- Eager load signal patches (select_related) ---

    original_related_populator_init = query.RelatedPopulator.__init__

    def _related_populator_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_related_populator_init(self, *args, **kwargs)
        self.__nplusone__ = {"args": args, "kwargs": kwargs}

    query.RelatedPopulator.__init__ = _related_populator_init  # type: ignore[method-assign]

    original_populate = query.RelatedPopulator.populate

    def _related_populator_populate(self: Any, *args: Any, **kwargs: Any) -> Any:
        ret = original_populate(self, *args, **kwargs)
        field = self.__nplusone__["args"][0]["field"]
        # Emit `load` for the populated child instance so it enters
        # the LazyListener's loaded set (enables N+1 detection on
        # FK fields of select_related instances).
        signals.load.send(
            signals.get_worker(),
            args=(self,) + tuple(args),
            kwargs=kwargs,
            context={},
            ret=ret,
            parser=parse_populate_load,
        )
        # Emit `eager_load` for unused eager load tracking.
        # Skip nullable FK fields — select_related is always valid for them.
        if not getattr(field, "null", False):
            signals.eager_load.send(
                signals.get_worker(),
                args=(self,) + tuple(args),
                kwargs=kwargs,
                context={},
                parser=parse_eager_select,
            )
        return ret

    query.RelatedPopulator.populate = _related_populator_populate  # type: ignore[method-assign]

    # --- Eager load signal patches (prefetch_related) ---

    prefetch_one_level_inner = query.prefetch_one_level  # already designalify'd

    def _prefetch_one_level_eager(*args: Any, **kwargs: Any) -> Any:
        ret = prefetch_one_level_inner(*args, **kwargs)
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

    query.prefetch_one_level = _prefetch_one_level_eager

    # --- Touch on queryset indexing ---

    original_getitem_queryset = query.QuerySet.__getitem__

    def _getitem_queryset(self: Any, index: Any) -> Any:
        if self._prefetch_done:
            signals.touch.send(
                get_worker(),
                args=(self,),
                parser=parse_fetch_all,
            )
        return original_getitem_queryset(self, index)

    query.QuerySet.__getitem__ = _getitem_queryset  # type: ignore[method-assign]
