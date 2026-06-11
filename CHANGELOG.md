## v1.1.3 (2026-06-11)

### Fix

- prevent per-request receiver leaks with thread-safe signal cleanup

## v1.1.2 (2026-06-08)

### Fix

- use strong Blinker receivers for scoped listener methods

## v1.1.1 (2026-05-24)

### Fix

- emit touch signal from ManyToManyDescriptor.__get__ for prefetched M2M fields

## v1.1.0 (2026-05-23)

### Feat

- add NPLUSONE_EXCLUDE_URLS to skip detection by URL prefix

## v1.0.1 (2026-05-23)

### Fix

- guard signalify_queryset against non-QuerySet return values
- use contextvars for ASGI thread safety and add GenericRelation touch hook

## v1.0.0 (2026-05-22)

### Feat

- port nplusone library with modern Python 3.11+, full type hints, and false positive fixes
- initialize project

### Fix

- use dynamic PKs in Django tests for parallel CI compatibility

### Refactor

- guard ORM monkey patches behind apply_patches() for zero prod overhead
