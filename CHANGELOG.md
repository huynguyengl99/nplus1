## v1.0.0 (2026-05-22)

### Feat

- port nplusone library with modern Python 3.11+, full type hints, and false positive fixes
- initialize project

### Fix

- use dynamic PKs in Django tests for parallel CI compatibility

### Refactor

- guard ORM monkey patches behind apply_patches() for zero prod overhead
