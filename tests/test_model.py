"""Tests for the UCH domain model."""

from __future__ import annotations

import pytest

from montador_uch.model import AggregationLevel, GeneratingUnit, HydroPlant, UnitGroup


def _group(index: int, total_mw: float, count: int, min_mw: float) -> UnitGroup:
    return UnitGroup(
        index=index,
        max_power_mw=total_mw,
        units=tuple(
            GeneratingUnit(index=position + 1, min_power_mw=min_mw, max_power_mw=total_mw / count)
            for position in range(count)
        ),
    )


class TestAggregationLevel:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Unidade", AggregationLevel.UNIT),
            ("Conjunto", AggregationLevel.GROUP),
            ("Usina", AggregationLevel.PLANT),
        ],
    )
    def test_from_label(self, label: str, expected: AggregationLevel) -> None:
        assert AggregationLevel.from_label(label) is expected

    def test_dessem_codes(self) -> None:
        assert (AggregationLevel.UNIT, AggregationLevel.GROUP, AggregationLevel.PLANT) == (1, 2, 3)

    @pytest.mark.parametrize("label", ["Sem UCH", "conjunto", "CONJUNTO", "", "Usinas"])
    def test_unknown_label_raises_naming_it(self, label: str) -> None:
        with pytest.raises(ValueError, match=r"Unknown aggregation label"):
            AggregationLevel.from_label(label)

    def test_error_message_contains_the_label(self) -> None:
        with pytest.raises(ValueError, match=r"'Reservatorio'"):
            AggregationLevel.from_label("Reservatorio")


class TestGeneratingUnit:
    def test_valid(self) -> None:
        unit = GeneratingUnit(index=2, min_power_mw=101.0, max_power_mw=152.0)
        assert unit.index == 2
        assert unit.min_power_mw == pytest.approx(101.0)
        assert unit.max_power_mw == pytest.approx(152.0)

    @pytest.mark.parametrize("index", [0, -1])
    def test_non_positive_index_raises(self, index: int) -> None:
        with pytest.raises(ValueError, match=r"Unit index must be positive"):
            GeneratingUnit(index=index, min_power_mw=1.0, max_power_mw=2.0)

    def test_negative_minimum_raises_naming_unit(self) -> None:
        with pytest.raises(ValueError, match=r"Unit 3 minimum power must not be negative"):
            GeneratingUnit(index=3, min_power_mw=-1.0, max_power_mw=2.0)

    def test_negative_maximum_raises_naming_unit(self) -> None:
        with pytest.raises(ValueError, match=r"Unit 3 maximum power must not be negative"):
            GeneratingUnit(index=3, min_power_mw=1.0, max_power_mw=-2.0)

    def test_minimum_above_maximum_raises(self) -> None:
        with pytest.raises(ValueError, match=r"Unit 1 minimum power 40.5 exceeds its maximum 39.3"):
            GeneratingUnit(index=1, min_power_mw=40.5, max_power_mw=39.3)

    def test_equal_limits_are_accepted(self) -> None:
        unit = GeneratingUnit(index=1, min_power_mw=23.0, max_power_mw=23.0)
        assert unit.min_power_mw == pytest.approx(unit.max_power_mw)

    def test_float_noise_does_not_trip_the_limit_check(self) -> None:
        GeneratingUnit(index=1, min_power_mw=23.0 + 1e-12, max_power_mw=23.0)

    def test_is_frozen(self) -> None:
        unit = GeneratingUnit(index=1, min_power_mw=1.0, max_power_mw=2.0)
        with pytest.raises(AttributeError):
            unit.index = 2  # type: ignore[misc]


class TestUnitGroup:
    def test_min_power_is_the_common_unit_minimum(self) -> None:
        group = _group(index=1, total_mw=912.0, count=6, min_mw=101.0)
        assert group.min_power_mw == pytest.approx(101.0)
        assert group.max_power_mw == pytest.approx(912.0)
        assert len(group.units) == 6

    @pytest.mark.parametrize("index", [0, -2])
    def test_non_positive_index_raises(self, index: int) -> None:
        with pytest.raises(ValueError, match=r"Group index must be positive"):
            UnitGroup(
                index=index,
                max_power_mw=10.0,
                units=(GeneratingUnit(index=1, min_power_mw=1.0, max_power_mw=10.0),),
            )

    def test_negative_maximum_raises_naming_group(self) -> None:
        with pytest.raises(ValueError, match=r"Group 2 maximum power must not be negative"):
            UnitGroup(
                index=2,
                max_power_mw=-10.0,
                units=(GeneratingUnit(index=1, min_power_mw=1.0, max_power_mw=10.0),),
            )

    def test_empty_units_raises(self) -> None:
        with pytest.raises(ValueError, match=r"Group 1 has no generating units"):
            UnitGroup(index=1, max_power_mw=10.0, units=())

    def test_non_unique_unit_indices_raises(self) -> None:
        unit = GeneratingUnit(index=1, min_power_mw=1.0, max_power_mw=5.0)
        with pytest.raises(ValueError, match=r"Group 1 has non-unique unit indices \[1, 1\]"):
            UnitGroup(index=1, max_power_mw=10.0, units=(unit, unit))

    def test_differing_unit_minima_raises(self) -> None:
        units = (
            GeneratingUnit(index=1, min_power_mw=10.0, max_power_mw=50.0),
            GeneratingUnit(index=2, min_power_mw=12.0, max_power_mw=50.0),
        )
        with pytest.raises(ValueError, match=r"Group 4 units have differing minimum powers"):
            UnitGroup(index=4, max_power_mw=100.0, units=units)

    def test_group_minimum_above_group_total_raises(self) -> None:
        """JAURU group 2 in the real workbook: a single unit whose start-up power exceeds it."""
        units = (GeneratingUnit(index=1, min_power_mw=39.4, max_power_mw=39.4),)
        with pytest.raises(
            ValueError, match=r"Group 2 minimum power 40.5 exceeds its maximum 39.4"
        ):
            UnitGroup(
                index=2,
                max_power_mw=39.4,
                units=(GeneratingUnit(index=1, min_power_mw=40.5, max_power_mw=40.5),),
            )
        assert UnitGroup(index=2, max_power_mw=39.4, units=units).min_power_mw == pytest.approx(
            39.4
        )

    def test_float_noise_in_minima_is_tolerated(self) -> None:
        units = (
            GeneratingUnit(index=1, min_power_mw=10.0, max_power_mw=50.0),
            GeneratingUnit(index=2, min_power_mw=10.0 + 1e-12, max_power_mw=50.0),
        )
        assert UnitGroup(index=1, max_power_mw=100.0, units=units).min_power_mw == pytest.approx(
            10.0
        )


class TestHydroPlant:
    def test_derived_limits_over_two_groups(self) -> None:
        plant = HydroPlant(
            code=6,
            name="FURNAS",
            aggregation=AggregationLevel.GROUP,
            groups=(
                _group(index=1, total_mw=912.0, count=6, min_mw=101.0),
                _group(index=2, total_mw=304.0, count=2, min_mw=101.0),
            ),
        )

        assert plant.max_power_mw == pytest.approx(1216.0)
        assert plant.min_power_mw == pytest.approx(101.0)
        assert len(plant.units) == 8
        assert [unit.index for unit in plant.units] == [1, 2, 3, 4, 5, 6, 1, 2]

    def test_min_power_is_the_smallest_unit_minimum(self) -> None:
        plant = HydroPlant(
            code=10,
            name="MIXED",
            aggregation=AggregationLevel.PLANT,
            groups=(
                _group(index=1, total_mw=100.0, count=2, min_mw=30.0),
                _group(index=2, total_mw=60.0, count=3, min_mw=12.0),
            ),
        )

        assert plant.min_power_mw == pytest.approx(12.0)
        assert plant.max_power_mw == pytest.approx(160.0)

    def test_non_positive_code_raises_naming_plant(self) -> None:
        with pytest.raises(ValueError, match=r"Plant 'X' code index must be positive"):
            HydroPlant(
                code=0,
                name="X",
                aggregation=AggregationLevel.GROUP,
                groups=(_group(index=1, total_mw=10.0, count=1, min_mw=1.0),),
            )

    def test_empty_groups_raises_naming_plant(self) -> None:
        with pytest.raises(ValueError, match=r"Plant 6 \(FURNAS\) has no unit groups"):
            HydroPlant(code=6, name="FURNAS", aggregation=AggregationLevel.GROUP, groups=())

    def test_non_unique_group_indices_raises_naming_plant(self) -> None:
        group = _group(index=1, total_mw=10.0, count=1, min_mw=1.0)
        with pytest.raises(
            ValueError, match=r"Plant 6 \(FURNAS\) has non-unique group indices \[1, 1\]"
        ):
            HydroPlant(
                code=6,
                name="FURNAS",
                aggregation=AggregationLevel.GROUP,
                groups=(group, group),
            )

    def test_is_frozen(self) -> None:
        plant = HydroPlant(
            code=1,
            name="A",
            aggregation=AggregationLevel.GROUP,
            groups=(_group(index=1, total_mw=10.0, count=1, min_mw=1.0),),
        )
        with pytest.raises(AttributeError):
            plant.code = 2  # type: ignore[misc]
