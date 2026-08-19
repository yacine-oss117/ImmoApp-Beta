from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.widgets.location_multi_select import LocationMultiSelect

pytestmark = pytest.mark.ui


def test_location_chip_area_is_hidden_when_empty_and_grows_adaptively(qapp) -> None:
    widget = LocationMultiSelect()
    widget.resize(420, 240)
    widget.show()
    qapp.processEvents()

    assert widget._chips_scroll.isHidden() is True

    widget.setValue("Hydra")
    qapp.processEvents()
    one_row_height = widget._chips_scroll.maximumHeight()

    assert widget._chips_scroll.isHidden() is False
    assert 36 <= one_row_height <= 48

    widget.setValue("; ".join(f"Location {index}" for index in range(12)))
    qapp.processEvents()
    expanded_height = widget._chips_scroll.maximumHeight()

    assert expanded_height >= one_row_height
    assert expanded_height <= 120
