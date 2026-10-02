import random
from collections import deque

import numpy as np
import pytest

from inu_voice.audio import RingBuffer


def ramp(start: int, count: int) -> np.ndarray:
    return np.arange(start, start + count, dtype=np.float32)


def test_rejects_non_positive_capacity() -> None:
    with pytest.raises(ValueError, match="positive"):
        RingBuffer(0)


def test_round_trip_preserves_order() -> None:
    ring = RingBuffer(8)
    assert ring.write(ramp(0, 5)) == 5
    np.testing.assert_array_equal(ring.read(), ramp(0, 5))
    assert ring.available() == 0


def test_wraps_around_the_end() -> None:
    ring = RingBuffer(8)
    ring.write(ramp(0, 6))
    ring.read()
    assert ring.write(ramp(6, 6)) == 6  # crosses the physical end of the array
    np.testing.assert_array_equal(ring.read(), ramp(6, 6))


def test_full_buffer_accepts_only_what_fits() -> None:
    ring = RingBuffer(4)
    assert ring.write(ramp(0, 6)) == 4
    assert ring.free() == 0
    assert ring.write(ramp(6, 1)) == 0
    np.testing.assert_array_equal(ring.read(), ramp(0, 4))


def test_read_into_fills_what_is_available() -> None:
    ring = RingBuffer(8)
    ring.write(ramp(0, 3))
    out = np.full(5, -1, dtype=np.float32)
    assert ring.read_into(out) == 3
    np.testing.assert_array_equal(out[:3], ramp(0, 3))
    assert (out[3:] == -1).all()  # untouched: the caller decides what silence is


def test_discard_drops_only_audio_written_before_the_request() -> None:
    ring = RingBuffer(16)
    ring.write(ramp(0, 6))
    ring.request_discard()
    assert ring.available() == 6  # nothing changes until the consumer acts
    ring.write(ramp(100, 3))
    np.testing.assert_array_equal(ring.read(), ramp(100, 3))


def test_matches_a_reference_queue_under_random_operations() -> None:
    rng = random.Random(1234)
    ring = RingBuffer(37)
    model: deque[float] = deque()
    counter = 0
    discard_mark: int | None = None  # model length when discard was requested

    for _ in range(5_000):
        op = rng.random()
        if op < 0.45:
            count = rng.randint(0, 50)
            written = ring.write(ramp(counter, count))
            assert written == min(count, 37 - len(model))
            model.extend(ramp(counter, written).tolist())
            counter += count
        elif op < 0.9:
            if discard_mark is not None:
                for _ in range(discard_mark):
                    model.popleft()
                discard_mark = None
            out = np.empty(rng.randint(0, 50), dtype=np.float32)
            got = ring.read_into(out)
            expected = [model.popleft() for _ in range(min(len(out), len(model)))]
            assert got == len(expected)
            np.testing.assert_array_equal(out[:got], expected)
        else:
            ring.request_discard()
            discard_mark = len(model)
        assert ring.available() + ring.free() == ring.capacity
