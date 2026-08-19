from __future__ import annotations

from server.api import adaptive_batch


def test_adaptive_batch_process_handles_empty_input() -> None:
    processed = adaptive_batch.adaptive_batch_process([], lambda _item: None, label="empty")
    assert processed == 0


def test_adaptive_batch_process_processes_all_items(monkeypatch) -> None:
    seen: list[int] = []
    monkeypatch.setattr(adaptive_batch, "_system_load_ratio", lambda: 0.1)
    monkeypatch.setattr(adaptive_batch.time, "sleep", lambda _seconds: None)
    processed = adaptive_batch.adaptive_batch_process(
        [1, 2, 3, 4, 5],
        lambda item: seen.append(item),
        batch_size=2,
        label="unit",
    )
    assert processed == 5
    assert seen == [1, 2, 3, 4, 5]


def test_system_load_ratio_is_non_negative_float() -> None:
    ratio = adaptive_batch._system_load_ratio()
    assert isinstance(ratio, float)
    assert ratio >= 0.0
