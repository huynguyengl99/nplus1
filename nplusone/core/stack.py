"""Stack introspection for identifying the source of N+1 queries."""

import inspect

PATTERNS = ["site-packages", "pytest", "nplusone"]


def get_caller(
    patterns: list[str] | None = None,
) -> inspect.FrameInfo | None:
    """Get the calling frame, excluding library and test frames."""
    frames = inspect.stack()
    patterns = patterns or PATTERNS
    return next(
        (
            each
            for each in frames
            if each[4] and not any(pattern in each[1] for pattern in patterns)
        ),
        None,
    )
