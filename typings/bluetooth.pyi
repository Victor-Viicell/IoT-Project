"""Minimal MicroPython bluetooth (BLE) stubs for editor type checking only."""

from typing import Any, Callable, Sequence

FLAG_READ: int
FLAG_WRITE: int
FLAG_NOTIFY: int
FLAG_INDICATE: int
FLAG_WRITE_NO_RESPONSE: int

def advertising_payload(
    *,
    limited_disc: bool = False,
    br_edr: bool = False,
    name: str | None = None,
    services: Sequence[str] | None = None,
    appearance: int = 0,
    manufacturer: bytes | None = None,
) -> bytes: ...

def uuid128(uuid: str) -> int: ...

class BLE:
    def __init__(self) -> None: ...
    def active(self, is_active: bool | None = None) -> bool: ...
    def config(self, *, mac: bytes | None = ..., gap_name: str | None = ..., **kwargs: Any) -> Any: ...
    def irq(self, handler: Callable[..., Any]) -> None: ...
    def gap_advertise(
        self,
        interval_us: int | None,
        *,
        adv_data: bytes | None = ...,
        resp_data: bytes | None = ...,
        connectable: bool = ...,
    ) -> None: ...
    def gatts_register_services(self, services: Any) -> tuple[tuple[int, ...], ...]: ...
    def gatts_set_buffer(self, value_handle: int, len: int, append: bool = False) -> None: ...
    def gatts_write(self, value_handle: int, data: bytes | str, send_update: bool = False) -> None: ...
    def gatts_read(self, value_handle: int) -> bytes: ...
    def gatts_notify(self, conn_handle: int, value_handle: int, data: bytes | str | None = None) -> None: ...
