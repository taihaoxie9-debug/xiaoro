from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident

import pytest

from app.guide.adapters.state import InMemorySessionLocks


def test_same_session_is_serialized() -> None:
    locks = InMemorySessionLocks(stripes=8)
    entered = Event()
    release = Event()
    order: list[str] = []

    def first() -> None:
        with locks.hold("s-1"):
            order.append("first")
            entered.set()
            release.wait(timeout=2)

    def second() -> None:
        entered.wait(timeout=2)
        with locks.hold("s-1"):
            order.append("second")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(first)
        second_future = pool.submit(second)
        assert entered.wait(timeout=2)
        assert order == ["first"]
        release.set()
        first_future.result(timeout=2)
        second_future.result(timeout=2)

    assert order == ["first", "second"]


def test_lock_storage_stays_bounded_for_many_sessions() -> None:
    locks = InMemorySessionLocks(stripes=8)

    for index in range(1000):
        with locks.hold(f"session-{index}"):
            pass

    assert locks.stripe_count == 8


def test_lock_can_be_released_by_a_different_thread() -> None:
    locks = InMemorySessionLocks(stripes=8)
    manager = locks.hold("s-1")

    def enter() -> int:
        manager.__enter__()
        return get_ident()

    with ThreadPoolExecutor(max_workers=1) as pool:
        acquiring_thread = pool.submit(enter).result(timeout=2)
        assert acquiring_thread != get_ident()
        manager.__exit__(None, None, None)

    with locks.hold("s-1"):
        pass


@pytest.mark.parametrize("stripes", [0, -1])
def test_requires_positive_stripe_count(stripes: int) -> None:
    with pytest.raises(ValueError, match="stripes must be positive"):
        InMemorySessionLocks(stripes=stripes)
