"""Synthetic reviewed drafts (invented prices) shared by the SQL export tests."""

from __future__ import annotations

import copy
from typing import Any

NASTY = "O'Brien \\ \"q\" ; -- /* x */ %s\nline2 ñ Ü 日本 '); drop table quotes.pricing_items; --"


def valid_draft() -> dict[str, Any]:
    return {
        "pricing_items": [
            {
                "id": "alpha-tour",
                "name_es": NASTY,
                "name_en": "Alpha tour",
                "category": "activity",
                "unit": "person",
                "duration_days": None,
                "price_pen": "12.34",
                "child_price_pen": "7.50",
                "active": True,
                "notes": "synthetic note",
                "source_name": "ALPHA  TOUR",
                "needs_review": False,
                "review_hint": "confirm the unit",
            },
            {
                "id": "beta-transport-2-days",
                "name_es": "Beta transporte 2 dias",
                "name_en": "Beta transport, 2 days",
                "category": "transport",
                "unit": "group",
                "duration_days": 2,
                "price_pen": "310.00",
                "child_price_pen": None,
                "active": True,
                "notes": None,
                "needs_review": False,
            },
        ],
        "local_payments": [
            {
                "id": "gamma-ticket",
                "name_es": "Boleto gamma",
                "name_en": "Gamma ticket",
                "prices": {
                    "latin_american_adult": "20.50",
                    "foreign_adult": "55.50",
                    "child_6_15": "10.25",
                },
                "active": True,
                "notes": None,
                "needs_review": False,
            }
        ],
    }


def mutate(**changes: Any) -> dict[str, Any]:
    """valid_draft() with first pricing item fields replaced (dotted keys not supported)."""
    draft = copy.deepcopy(valid_draft())
    draft["pricing_items"][0].update(changes)
    return draft
