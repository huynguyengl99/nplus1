# nplusone

Detect the N+1 queries problem in Python ORMs — SQLAlchemy, Peewee, and Django ORM.

A modern rewrite of the [original nplusone](https://github.com/jmcarp/nplusone) library, targeting Python 3.11+ with full type annotations, SQLAlchemy 2.0 support, and fixes for false positives found in production Django+DRF codebases.

[![PyPI](https://img.shields.io/pypi/v/nplusone)](https://pypi.org/project/nplusone/)
[![Python](https://img.shields.io/pypi/pyversions/nplusone)](https://pypi.org/project/nplusone/)
[![Tests](https://github.com/huynguyengl99/nplus1/actions/workflows/test.yml/badge.svg)](https://github.com/huynguyengl99/nplus1/actions)
[![Coverage](https://codecov.io/gh/huynguyengl99/nplus1/branch/main/graph/badge.svg)](https://codecov.io/gh/huynguyengl99/nplus1)

## Installation

```bash
pip install nplusone
```

With optional ORM/framework dependencies:

```bash
pip install nplusone[django]           # Django 4.2+
pip install nplusone[sqlalchemy]       # SQLAlchemy 2.0+
pip install nplusone[flask]            # Flask + Flask-SQLAlchemy
pip install nplusone[peewee]           # Peewee 3.15+
```

## Quick Start

### Django

Add the middleware to your **dev** settings:

```python
# settings/dev.py
MIDDLEWARE = [
    ...
    "nplusone.ext.django.NPlusOneMiddleware",
    ...
]

NPLUSONE_ENABLED = True    # set False in prod (zero overhead)
NPLUSONE_LOG = True        # log detections (default)
NPLUSONE_RAISE = True      # raise exceptions in dev/test
```

### Flask + SQLAlchemy

```python
from nplusone.ext.flask_sqlalchemy import NPlusOne

app = Flask(__name__)
NPlusOne(app)
```

### Standalone (any code)

```python
from nplusone.core.profiler import Profiler

with Profiler():
    users = session.query(User).all()
    for user in users:
        user.addresses  # NPlusOneError raised
```

### Celery

```python
from nplusone.ext.celery import NPlusOneCelery

app = Celery("myapp")
NPlusOneCelery(app)
```

Or manually with signals:

```python
from celery.signals import task_prerun, task_postrun
from nplusone.core.profiler import setup, teardown

@task_prerun.connect()
def on_prerun(**kwargs):
    setup()

@task_postrun.connect()
def on_postrun(**kwargs):
    teardown()
```

## What It Detects

### N+1 lazy loads

```python
users = User.objects.all()          # 1 query
for user in users:
    print(user.addresses)           # N queries — flagged!
```

**Fix:** use `select_related` or `prefetch_related`:

```python
users = User.objects.select_related("addresses").all()
```

### Unnecessary eager loads

```python
users = User.objects.select_related("occupation").all()
for user in users:
    print(user.name)                # occupation never accessed — flagged!
```

## Configuration

All settings work across Django, Flask, and Celery:

| Setting | Default | Description |
|---------|---------|-------------|
| `NPLUSONE_ENABLED` | `True` | Master switch. Set `False` in prod for zero overhead. |
| `NPLUSONE_LOG` | `True` | Log detections to the `nplusone` logger. |
| `NPLUSONE_RAISE` | `False` | Raise `NPlusOneError` on detection. |
| `NPLUSONE_WHITELIST` | `[]` | List of rule dicts to suppress specific warnings. |
| `NPLUSONE_LOGGER` | `logging.getLogger("nplusone")` | Custom logger instance. |
| `NPLUSONE_LOG_LEVEL` | `DEBUG` | Log level for detections. |
| `NPLUSONE_DEBUG` | `False` | Verbose signal logging to `nplusone.debug` logger. |
| `NPLUSONE_REPORT_MODE` | `"immediate"` | `"immediate"` or `"batch"`. Batch collects all detections and reports at end of request. |
| `NPLUSONE_SKIP_EAGER_ON_ERROR` | `True` | Skip eager load checks on error responses (>= 400). |
| `NPLUSONE_EAGER_LOAD_SKIP` | `None` | Callable `(request, response) -> bool` for custom skip logic. |
| `NPLUSONE_SKIP_EMPTY_PREFETCH` | `False` | Skip flagging `prefetch_related` that returns zero rows. |

### Whitelisting

Suppress specific warnings by model, field, or pattern:

```python
NPLUSONE_WHITELIST = [
    {"model": "User", "field": "profile"},       # exact match
    {"model": "myapp.User"},                      # Django app_label.Model format
    {"model": "User*"},                           # fnmatch wildcard
    {"label": "unused_eager_load"},               # suppress all eager load warnings
]
```

### Prod/Dev Split

Only add the middleware in dev/test settings — no need for it in production:

```python
# settings/dev.py (or settings/test.py)
MIDDLEWARE = [
    ...
    "nplusone.ext.django.NPlusOneMiddleware",
    ...
]
NPLUSONE_RAISE = True
```

No `INSTALLED_APPS` entry is needed — the ORM patches are applied
automatically when the middleware is imported.

For Celery, use `NPLUSONE_ENABLED` to control whether detection runs:

```python
# settings/base.py
NPLUSONE_ENABLED = False   # Celery setup() is a no-op

# settings/dev.py
NPLUSONE_ENABLED = True    # Celery detection active
```

## Debug Mode

Enable `NPLUSONE_DEBUG = True` to see every signal fire during a request:

```
[nplusone.debug] REQUEST START: GET /api/orders/
[nplusone.debug] EAGER_REGISTER: Order.customer (5 instances) at views.py:42 in get_queryset
[nplusone.debug] EAGER_ACCESS: Order.customer (1 instances) at serializers.py:18 in to_representation
[nplusone.debug] DETECTED: Potential unnecessary eager load on Order.shipping_address
[nplusone.debug] REQUEST END: GET /api/orders/ → 200
```

Detection messages include the registration site (inspired by
[django-zeal](https://github.com/taobojlen/django-zeal)'s `ZEAL_SHOW_ALL_CALLERS`):

```
Potential unnecessary eager load detected on `Order.shipping_address`
  Registered at: myapp/views.py:42 in get_queryset
                 qs.select_related("customer", "shipping_address")
```

## Comparison

### vs. [jmcarp/nplusone](https://github.com/jmcarp/nplusone) (original)

This library is a ground-up rewrite of the original nplusone, which has been
unmaintained since 2020. We preserve the same detection architecture
(blinker signals + ORM monkey-patching) but modernize everything else:

| | Original nplusone | This library |
|---|---|---|
| Python | 2.7+ / 3.3+ | 3.11+ |
| Type hints | None | Full (mypy strict + pyright strict) |
| SQLAlchemy | 1.x only | 2.0+ |
| Django | 1.8+ (compat code) | 4.2 – 5.2 (clean) |
| Nullable FK | False positive | Skipped (valid optimization) |
| MTI / Polymorphic | False positives | PK-based cross-model matching |
| Error responses | False positive | Skipped on 4xx/5xx (configurable) |
| Celery | Not supported | `NPlusOneCelery(app)` + `setup()`/`teardown()` |
| Debug/trace mode | Not available | `NPLUSONE_DEBUG` with full signal logging |
| Stack traces | Not in messages | Registration site in every detection |
| Batch reporting | Not available | `NPLUSONE_REPORT_MODE = "batch"` |
| Prod switch | Not available | `NPLUSONE_ENABLED = False` (zero overhead) |
| Dependencies | `six`, `blinker` | `blinker` only |

### vs. [django-zeal](https://github.com/taobojlen/django-zeal)

django-zeal is a Django-only N+1 detector with a different approach.

| | django-zeal | This library |
|---|---|---|
| ORMs | Django only | Django, SQLAlchemy, Peewee |
| Detect N+1 lazy loads | Yes | Yes |
| Detect unused eager loads | No | Yes |
| Detect `.defer()`/`.only()` issues | Yes | No |
| Configurable threshold | Yes (`ZEAL_NPLUSONE_THRESHOLD`) | No (flags on first repeat) |
| Non-invasive in prod | Yes (no patching when inactive) | Yes (`NPLUSONE_ENABLED = False` skips all setup) |
| Stack traces | Yes (`ZEAL_SHOW_ALL_CALLERS`) | Yes (always included) |
| Celery | Manual `setup()`/`teardown()` | `NPlusOneCelery(app)` or manual |
| Batch reporting | No | Yes |

**Choose nplusone** if you need multi-ORM support, unused eager load detection,
or work with complex Django patterns (MTI, polymorphic models, DRF).

**Choose django-zeal** if you only use Django and want `.defer()`/`.only()`
detection or configurable thresholds.

## Development

```bash
# Setup
uv sync

# Run tests
python -m pytest tests/

# Run tests for specific ORM
tox -e py311-django52
tox -e py311-sqlalchemy
tox -e py311-peewee
tox -e py311-flask

# Lint and type check
ruff check nplusone/ tests/
python -m mypy nplusone/
npx pyright

# Coverage
python -m pytest tests/ --cov=nplusone --cov-report=term-missing
```

### Multi-version Testing

```bash
# Full matrix
tox

# Specific Python + Django version
tox -e py312-django51
tox -e py313-django42
```

### Docker (PostgreSQL)

```bash
docker compose up -d
cp .env.EXAMPLE .env
python -m pytest tests/testapp/
```

## License

MIT. See [LICENSE](LICENSE).
