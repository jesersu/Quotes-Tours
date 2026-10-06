"""The reviewable catalog draft: a YAML file the owner edits before generating SQL."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml

from quotes.infrastructure.output_file import OutputExists, write_new_file

__all__ = ["OutputExists", "dump_draft", "load_draft", "write_new_file"]

HEADER = """\
# Catalog draft generated from the price spreadsheet. PRIVATE: do not commit it.
#
# How to review (then run `quotes catalog sql <this file>`):
#   - Every entry starts with needs_review: true. Check its fields (unit, English name,
#     category, child_price_pen, ...), follow review_hint, then set needs_review: false.
#   - Local payments (paid by the tourist on site, information only) need all three prices.
#   - Keep price_pen as a quoted string with two decimals, for example "12.34".
#   - source_name is the original spreadsheet text, kept for reference only.
"""


def dump_draft(draft: Mapping[str, Any]) -> str:
    body = yaml.safe_dump(
        dict(draft), sort_keys=False, allow_unicode=True, default_flow_style=False, width=100
    )
    return f"{HEADER}\n{body}"


def load_draft(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Draft is not valid YAML: {type(exc).__name__}") from exc
