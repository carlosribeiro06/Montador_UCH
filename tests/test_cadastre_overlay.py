"""Tests for the `AC` cadastre change overlay, on hand-built `PlantRecord`s."""

from __future__ import annotations

import pytest

from montador_uch.cadastre_changes import (
    CadastreChangeError,
    GroupCountChange,
    UnitCountChange,
    UnitPowerChange,
)
from montador_uch.cadastre_overlay import apply_cadastre_changes
from montador_uch.model import AggregationLevel
from montador_uch.spreadsheet import (
    MAX_GROUPS,
    START_UP_POWER_COLUMN,
    GroupRecord,
    PlantRecord,
    SpreadsheetError,
    build_plant,
    group_column,
)

_UNUSED_POSITION: tuple[int, float | None, float | None] = (0, None, None)


def _record(
    code: int,
    name: str,
    group_count: int,
    *positions: tuple[int, float | None, float | None],
    row_number: int = 3,
    aggregation: AggregationLevel = AggregationLevel.GROUP,
) -> PlantRecord:
    """A `PlantRecord` from up to `MAX_GROUPS` `(unit_count, min_mw, max_mw)` tuples.

    Positions beyond `len(positions)` default to `_UNUSED_POSITION`, mirroring how
    `spreadsheet.read_records` leaves the sheet's unused group columns.
    """
    padded = list(positions) + [_UNUSED_POSITION] * (MAX_GROUPS - len(positions))
    groups = tuple(
        GroupRecord(
            index=index + 1, unit_count=unit_count, min_power_mw=min_mw, max_power_mw=max_mw
        )
        for index, (unit_count, min_mw, max_mw) in enumerate(padded)
    )
    return PlantRecord(
        code=code,
        name=name,
        row_number=row_number,
        aggregation=aggregation,
        group_count=group_count,
        groups=groups,
    )


def test_no_changes_matches_build_plant() -> None:
    record = _record(1, "A", 2, (2, 5.0, 20.0), (3, 10.0, 60.0))

    result = apply_cadastre_changes([record], [])

    assert result.plants == [build_plant(record)]
    assert result.omitted == []
    assert result.changes_applied == 0
    assert result.changes_ignored == 0


def test_no_changes_propagates_build_plant_errors_unwrapped() -> None:
    """A deck without a relevant `AC` record reproduces `build_plant`'s errors exactly."""
    broken = _record(1, "A", 1, (2, 5.0, None))

    with pytest.raises(SpreadsheetError, match=r"'Potencia_maxima' is empty"):
        apply_cadastre_changes([broken], [])


def test_change_for_unknown_plant_is_ignored_and_counted() -> None:
    record = _record(1, "A", 1, (2, 5.0, 20.0))

    result = apply_cadastre_changes([record], [GroupCountChange(999, 1)])

    assert result.plants == [build_plant(record)]
    assert result.changes_applied == 0
    assert result.changes_ignored == 1


def test_unknown_plant_change_is_logged_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    record = _record(1, "A", 1, (2, 5.0, 20.0))

    with caplog.at_level("DEBUG", logger="montador_uch.cadastre_overlay"):
        apply_cadastre_changes([record], [GroupCountChange(999, 1)])

    assert "plant 999" in caplog.text


def test_unit_count_cut_with_reaffirmed_unit_power() -> None:
    """275-like: `NUMMAQ 3 10` with `POTEFE 3 390` cuts the unit count of group 3 to 10."""
    record = _record(275, "PLANT275", 3, (2, 25.0, 50.0), (5, 30.0, 900.0), (11, 35.0, 4290.0))

    result = apply_cadastre_changes(
        [record],
        [UnitCountChange(275, 3, 10), UnitPowerChange(275, 3, 390.0)],
    )

    [plant] = result.plants
    group = plant.groups[2]
    assert group.index == 3
    assert group.max_power_mw == pytest.approx(3900.0)
    assert len(group.units) == 10
    assert group.min_power_mw == pytest.approx(35.0)
    assert all(unit.max_power_mw == pytest.approx(390.0) for unit in group.units)
    assert result.changes_applied == 2


def test_new_group_promoted_by_numcon_keeps_its_zero_unit_min_power() -> None:
    """287-like: `NUMCON` promotes group 3, whose start-up power the workbook already carried
    at 0 units (the record position `_read_group_record` keeps verbatim)."""
    record = _record(
        287,
        "STO ANTONIO",
        2,
        (24, 21.0, 1759.2),
        (20, 11.0, 1392.0),
        (0, 21.0, None),
    )

    result = apply_cadastre_changes(
        [record],
        [GroupCountChange(287, 3), UnitCountChange(287, 3, 6), UnitPowerChange(287, 3, 69.6)],
    )

    [plant] = result.plants
    assert [group.index for group in plant.groups] == [1, 2, 3]
    new_group = plant.groups[2]
    assert new_group.max_power_mw == pytest.approx(417.6)
    assert len(new_group.units) == 6
    assert new_group.min_power_mw == pytest.approx(21.0)
    assert all(unit.max_power_mw == pytest.approx(69.6) for unit in new_group.units)
    assert all(unit.min_power_mw == pytest.approx(21.0) for unit in new_group.units)


def test_unit_count_change_without_power_change_keeps_the_original_unit_maximum() -> None:
    """`NUMMAQ` alone keeps the per-unit power the workbook total implied, `26 -> 20` units."""
    record = _record(1, "A", 1, (26, 11.0, 1809.6))

    result = apply_cadastre_changes([record], [UnitCountChange(1, 1, 20)])

    [plant] = result.plants
    group = plant.groups[0]
    expected_unit_max = 1809.6 / 26
    assert len(group.units) == 20
    assert group.max_power_mw == pytest.approx(20 * expected_unit_max)
    assert all(unit.max_power_mw == pytest.approx(expected_unit_max) for unit in group.units)


def test_untouched_group_keeps_the_exact_spreadsheet_total() -> None:
    """A group with no change keeps `Potencia_maxima` verbatim, not `unit_count * unit_max_mw`
    recomputed, which is not always bit-identical to the stored total."""
    record = _record(1, "A", 2, (11, 5.0, 100.0), (2, 5.0, 20.0))
    assert 11 * (100.0 / 11) != 100.0  # the recomputation this test guards against

    result = apply_cadastre_changes([record], [UnitCountChange(1, 2, 3)])

    [plant] = result.plants
    assert plant.groups[0].max_power_mw == 100.0


def test_group_count_shrink_drops_the_higher_groups() -> None:
    record = _record(1, "A", 3, (2, 5.0, 20.0), (3, 5.0, 30.0), (4, 5.0, 40.0))

    result = apply_cadastre_changes([record], [GroupCountChange(1, 2)])

    [plant] = result.plants
    assert [group.index for group in plant.groups] == [1, 2]
    assert plant.groups[0].max_power_mw == pytest.approx(20.0)
    assert plant.groups[1].max_power_mw == pytest.approx(30.0)


def test_unit_count_change_above_group_count_raises() -> None:
    record = _record(1, "A", 1, (2, 5.0, 20.0))

    with pytest.raises(
        CadastreChangeError, match=r"AC NUMMAQ group 2 exceeds the plant's current 1"
    ):
        apply_cadastre_changes([record], [UnitCountChange(1, 2, 3)])


def test_unit_power_change_above_group_count_raises() -> None:
    record = _record(1, "A", 1, (2, 5.0, 20.0))

    with pytest.raises(
        CadastreChangeError, match=r"AC POTEFE group 2 exceeds the plant's current 1"
    ):
        apply_cadastre_changes([record], [UnitPowerChange(1, 2, 30.0)])


def test_group_count_above_maximum_raises() -> None:
    record = _record(1, "A", 1, (2, 5.0, 20.0))

    with pytest.raises(CadastreChangeError, match=r"exceeding the workbook's maximum of 5"):
        apply_cadastre_changes([record], [GroupCountChange(1, MAX_GROUPS + 1)])


def test_new_group_without_potefe_and_blank_max_raises() -> None:
    record = _record(1, "A", 1, (2, 5.0, 20.0), _UNUSED_POSITION)

    with pytest.raises(CadastreChangeError, match=r"group 2 has no per-unit power"):
        apply_cadastre_changes([record], [GroupCountChange(1, 2), UnitCountChange(1, 2, 3)])


def test_new_group_without_potefe_on_a_zero_unit_position_blames_the_unit_count() -> None:
    """Plant-287 shape: the total is present but no units, so the message must not blame it."""
    record = _record(1, "A", 1, (2, 5.0, 20.0), (0, 21.0, 0.0))

    with pytest.raises(
        CadastreChangeError, match=r"group 2 no units, so its total in 'Potencia_maxima.1'"
    ):
        apply_cadastre_changes([record], [GroupCountChange(1, 2), UnitCountChange(1, 2, 3)])


def test_new_group_with_blank_min_power_raises_naming_the_column() -> None:
    record = _record(1, "A", 1, (2, 5.0, 20.0), _UNUSED_POSITION)
    expected_column = group_column(START_UP_POWER_COLUMN, 1)

    with pytest.raises(
        CadastreChangeError, match=rf"group 2 has no start-up power.*{expected_column!r}"
    ):
        apply_cadastre_changes(
            [record],
            [GroupCountChange(1, 2), UnitCountChange(1, 2, 3), UnitPowerChange(1, 2, 15.0)],
        )


def test_all_groups_zeroed_is_omitted_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    record = _record(87, "B ARARAS", 1, (2, 20.0, 40.0))

    with caplog.at_level("WARNING", logger="montador_uch.cadastre_overlay"):
        result = apply_cadastre_changes([record], [UnitCountChange(87, 1, 0)])

    assert result.plants == []
    [omitted] = result.omitted
    assert omitted.code == 87
    assert omitted.name == "B ARARAS"
    assert omitted.row_number == record.row_number
    assert omitted.reason == "all unit groups have zero units after AC changes"
    assert "plant 87 (B ARARAS)" in caplog.text
    assert "all unit groups have zero units" in caplog.text


def test_numcon_zero_is_omitted_with_its_own_reason(caplog: pytest.LogCaptureFixture) -> None:
    """`NUMCON 0` declares a plant with no groups; its groups keep their machines."""
    record = _record(1, "NO GROUPS", 2, (2, 5.0, 20.0), (3, 10.0, 60.0))

    with caplog.at_level("WARNING", logger="montador_uch.cadastre_overlay"):
        result = apply_cadastre_changes([record], [GroupCountChange(1, 0)])

    assert result.plants == []
    [omitted] = result.omitted
    assert omitted.code == 1
    assert omitted.reason == "AC NUMCON set the plant to zero unit groups"
    assert "all unit groups have zero units" not in caplog.text
    assert "AC NUMCON set the plant to zero unit groups" in caplog.text


def test_potefe_below_start_up_power_raises_with_plant_context() -> None:
    record = _record(1, "TIGHT", 1, (2, 50.0, 100.0))

    with pytest.raises(
        CadastreChangeError, match=r"plant 1 \(TIGHT\): Unit \d+ minimum power 50.0 exceeds"
    ):
        apply_cadastre_changes([record], [UnitPowerChange(1, 1, 40.0)])


def test_order_matters_dependent_change_before_group_count_change_raises() -> None:
    record = _record(1, "A", 1, (2, 5.0, 20.0))

    with pytest.raises(CadastreChangeError, match=r"AC NUMMAQ group 2 exceeds"):
        apply_cadastre_changes([record], [UnitCountChange(1, 2, 3), GroupCountChange(1, 2)])


def test_order_matters_group_count_change_first_succeeds() -> None:
    record = _record(1, "A", 1, (2, 5.0, 20.0), (0, 10.0, None))

    result = apply_cadastre_changes(
        [record],
        [GroupCountChange(1, 2), UnitCountChange(1, 2, 3), UnitPowerChange(1, 2, 12.0)],
    )

    [plant] = result.plants
    assert [group.index for group in plant.groups] == [1, 2]


def test_group_count_change_is_logged_matching_the_ticket_example(
    caplog: pytest.LogCaptureFixture,
) -> None:
    record = _record(287, "STO ANTONIO", 2, (24, 21.0, 1759.2), (26, 11.0, 1809.6))

    with caplog.at_level("INFO", logger="montador_uch.cadastre_overlay"):
        apply_cadastre_changes([record], [GroupCountChange(287, 3)])

    assert "Plant 287 (STO ANTONIO): NUMCON 2 -> 3" in caplog.text


def test_unit_count_change_is_logged_matching_the_ticket_example(
    caplog: pytest.LogCaptureFixture,
) -> None:
    record = _record(287, "STO ANTONIO", 2, (24, 21.0, 1759.2), (26, 11.0, 1809.6))

    with caplog.at_level("INFO", logger="montador_uch.cadastre_overlay"):
        apply_cadastre_changes([record], [UnitCountChange(287, 2, 20)])

    assert "Plant 287 (STO ANTONIO): group 2 units 26 -> 20" in caplog.text


def test_unit_power_change_is_logged_matching_the_ticket_example(
    caplog: pytest.LogCaptureFixture,
) -> None:
    record = _record(287, "STO ANTONIO", 2, (24, 21.0, 1759.2), (26, 11.0, 1809.6))

    with caplog.at_level("INFO", logger="montador_uch.cadastre_overlay"):
        apply_cadastre_changes([record], [UnitPowerChange(287, 2, 69.6)])

    assert "Plant 287 (STO ANTONIO): group 2 unit power 69.6 -> 69.6 MW" in caplog.text


def test_closing_summary_is_logged_at_info(caplog: pytest.LogCaptureFixture) -> None:
    known = _record(1, "A", 1, (2, 5.0, 20.0))

    with caplog.at_level("INFO", logger="montador_uch.cadastre_overlay"):
        result = apply_cadastre_changes([known], [GroupCountChange(999, 1)])

    assert result.plants == [build_plant(known)]
    assert "1 plant(s) built" in caplog.text
    assert "0 plant(s) omitted" in caplog.text
    assert "0 change(s) applied" in caplog.text
    assert "1 change(s) ignored" in caplog.text


def test_output_order_follows_the_records_order() -> None:
    first = _record(2, "SECOND CODE FIRST ROW", 1, (2, 5.0, 20.0))
    second = _record(1, "FIRST CODE SECOND ROW", 1, (2, 5.0, 20.0))

    result = apply_cadastre_changes([first, second], [])

    assert [plant.code for plant in result.plants] == [2, 1]
