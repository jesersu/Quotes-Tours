"""Travelers: adults plus children with ages, and the fare category each one pays."""

from __future__ import annotations

from dataclasses import dataclass

from quotes.domain.errors import InvalidPricingInput

FREE_UNDER_AGE = 6  # children below this age are free on everything
ADULT_FROM_AGE = 16  # assumption: 16-17 year olds are priced as adults
MAX_CHILD_AGE = 17


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class Travelers:
    adults: int
    child_ages: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not _is_int(self.adults) or self.adults < 1:
            raise InvalidPricingInput("Adults must be an integer of at least 1")
        object.__setattr__(self, "child_ages", tuple(self.child_ages))
        for age in self.child_ages:
            if not _is_int(age) or not 0 <= age <= MAX_CHILD_AGE:
                raise InvalidPricingInput(f"Child age must be an integer from 0 to 17: {age!r}")

    @property
    def total(self) -> int:
        return self.adults + len(self.child_ages)

    @property
    def full_fare_count(self) -> int:
        """Adults plus 16-17 year olds, who pay the adult fare."""
        return self.adults + sum(age >= ADULT_FROM_AGE for age in self.child_ages)

    @property
    def reduced_fare_children(self) -> int:
        """Children aged 6-15: pay the child price where one exists, else the adult price."""
        return sum(FREE_UNDER_AGE <= age < ADULT_FROM_AGE for age in self.child_ages)
