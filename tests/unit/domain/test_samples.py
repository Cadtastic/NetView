from netview.domain.samples import counter_rate


def test_rate_in_bits_per_second() -> None:
    assert counter_rate((1000, 0, 0), 2000, 500, 1000) == (8000.0, 4000.0)


def test_counter_going_backwards_gives_none() -> None:
    assert counter_rate((2000, 0, 0), 1000, 0, 1000) is None
    assert counter_rate((0, 2000, 0), 0, 1000, 1000) is None


def test_zero_or_negative_interval_gives_none() -> None:
    assert counter_rate((1000, 0, 5), 2000, 0, 5) is None
    assert counter_rate((1000, 0, 5), 2000, 0, 4) is None


def test_no_previous_reading_gives_none() -> None:
    assert counter_rate(None, 1000, 1000, 1000) is None


def test_unchanged_counters_are_a_zero_rate() -> None:
    assert counter_rate((10, 10, 0), 10, 10, 1000) == (0.0, 0.0)
