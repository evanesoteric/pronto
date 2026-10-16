from typing import Callable
from collections import defaultdict

_handlers: dict[str, list[Callable]] = defaultdict(list)


def on(event: str):
    def decorator(fn):
        _handlers[event].append(fn)
        return fn
    return decorator


def emit(event: str, **kwargs) -> None:
    for handler in _handlers[event]:
        handler(**kwargs)
