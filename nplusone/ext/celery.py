"""Celery integration for N+1 detection.

Provides automatic N+1 detection for Celery tasks via either:
1. Auto-setup: ``NPlusOneCelery(app)`` — zero-config, wraps all tasks
2. Manual setup: use ``setup()``/``teardown()`` with Celery signals

Auto-setup example::

    from celery import Celery
    from nplusone.ext.celery import NPlusOneCelery

    app = Celery("myapp")
    NPlusOneCelery(app)  # All tasks now have N+1 detection

Manual setup example::

    from celery.signals import task_prerun, task_postrun
    from nplusone.core.profiler import setup, teardown

    @task_prerun.connect()
    def on_prerun(**kwargs):
        setup()

    @task_postrun.connect()
    def on_postrun(**kwargs):
        teardown()
"""

from typing import Any

from celery.signals import task_postrun, task_prerun

from nplusone.core.profiler import setup, teardown


class NPlusOneCelery:
    """Celery extension for automatic N+1 query detection.

    Wraps all task executions with detection listeners. Configuration
    is loaded from Django settings (if available) or can be passed
    explicitly.

    Settings (from Django settings or explicit config):
    - NPLUSONE_LOG: Enable logging (default True)
    - NPLUSONE_RAISE: Enable exception raising (default False)
    - NPLUSONE_WHITELIST: List of rule dicts to suppress warnings
    - NPLUSONE_LOGGER: Custom logger instance
    - NPLUSONE_LOG_LEVEL: Custom log level
    """

    def __init__(
        self,
        app: Any | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.config = config
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Any) -> None:
        """Register task signal handlers on the Celery app."""
        task_prerun.connect(self._on_prerun)
        task_postrun.connect(self._on_postrun)

    def _on_prerun(self, **kwargs: Any) -> None:
        """Set up detection listeners before task execution."""
        setup(config=self.config)

    def _on_postrun(self, **kwargs: Any) -> None:
        """Tear down listeners and report findings after task execution."""
        teardown()
