import pytest

from quotes.domain.errors import InvalidPricingInput
from quotes.domain.travelers import Travelers


def test_adults_only():
    t = Travelers(adults=2)
    assert (t.full_fare_count, t.reduced_fare_children, t.total) == (2, 0, 2)


def test_children_under_six_are_free_and_not_counted_as_paying():
    t = Travelers(adults=2, child_ages=(0, 5))
    assert (t.full_fare_count, t.reduced_fare_children, t.total) == (2, 0, 4)


def test_children_six_to_fifteen_are_reduced_fare():
    t = Travelers(adults=1, child_ages=(6, 15))
    assert (t.full_fare_count, t.reduced_fare_children) == (1, 2)


def test_children_sixteen_and_seventeen_count_as_full_fare():
    t = Travelers(adults=1, child_ages=(16, 17))
    assert (t.full_fare_count, t.reduced_fare_children) == (3, 0)


@pytest.mark.parametrize("adults", [0, -1, True, 1.5])
def test_adults_must_be_integer_of_at_least_one(adults):
    with pytest.raises(InvalidPricingInput):
        Travelers(adults=adults)  # type: ignore[arg-type]


@pytest.mark.parametrize("age", [-1, 18, True, 7.5])
def test_child_age_must_be_integer_between_zero_and_seventeen(age):
    with pytest.raises(InvalidPricingInput):
        Travelers(adults=1, child_ages=(age,))  # type: ignore[arg-type]
