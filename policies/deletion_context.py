from contextlib import contextmanager
from contextvars import ContextVar

_allow_policydevice_delete = ContextVar(
    "allow_policydevice_delete",
    default=False,
)


def is_policydevice_delete_allowed():
    return _allow_policydevice_delete.get()


@contextmanager
def allow_policydevice_delete():
    token = _allow_policydevice_delete.set(True)
    try:
        yield
    finally:
        _allow_policydevice_delete.reset(token)