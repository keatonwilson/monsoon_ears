from ingestion.vad import _flags_to_segments, _merge_close


def test_flags_to_segments_basic():
    flags = [False, True, True, False, True, False]
    assert _flags_to_segments(flags) == [(1, 3), (4, 5)]


def test_flags_to_segments_closes_at_end():
    flags = [False, True, True, True]
    assert _flags_to_segments(flags) == [(1, 4)]


def test_flags_to_segments_all_silence():
    assert _flags_to_segments([False] * 10) == []


def test_flags_to_segments_all_speech():
    assert _flags_to_segments([True] * 5) == [(0, 5)]


def test_merge_close_combines_within_gap():
    # gap of 2 frames between (0,5) and (7,10) — merge with gap=3
    assert _merge_close([(0, 5), (7, 10)], max_gap_frames=3) == [(0, 10)]


def test_merge_close_preserves_distant():
    # gap of 5 frames — don't merge with gap=3
    assert _merge_close([(0, 5), (10, 15)], max_gap_frames=3) == [(0, 5), (10, 15)]


def test_merge_close_chains():
    # three runs all within gap distance collapse to one
    assert _merge_close([(0, 2), (3, 5), (6, 8)], max_gap_frames=2) == [(0, 8)]


def test_merge_close_empty():
    assert _merge_close([], max_gap_frames=5) == []
