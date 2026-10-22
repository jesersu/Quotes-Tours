import io
from datetime import date
from decimal import Decimal

import pytest
import yaml

from quotes import cli
from quotes.application.catalog import Catalog, CatalogEntry, CatalogIssue
from quotes.application.planner import (
    PlannedDay,
    PlannedItem,
    PlannedOption,
    PlannedRequest,
    PlannerUnavailable,
)
from quotes.cli import main
from quotes.domain.catalog import CatalogItem, PricingUnit
from quotes.domain.money import Currency, Money
from quotes.infrastructure.in_memory_catalog import InMemoryCatalogRepository
from quotes.infrastructure.settings import MissingSetting

# Synthetic numbers chosen so they cannot appear in the output by accident.
PRICE = "777.77"
MARGIN = "0.31"
MESSAGE = "Hello, we are the Zorro family and we want two days at the canyon."
CLIENT = "Zorro family"
HINT = "Ask whether the Zorro children need a car seat"


def entry(item_id: str, unit: PricingUnit) -> CatalogEntry:
    item = CatalogItem(item_id, item_id, Money(Decimal(PRICE), Currency.PEN), unit)
    return CatalogEntry(item, "tour", item_id, item_id)


def catalog() -> Catalog:
    return Catalog([entry("van", PricingUnit.PER_GROUP), entry("guide", PricingUnit.PER_DAY)], [])


def planned(**overrides) -> PlannedRequest:
    fields = {
        "client": CLIENT,
        "title": "Canyon, 2 days",
        "language": "en",
        "days": 2,
        "adults": 2,
        "child_ages": (8,),
        "options": (
            PlannedOption(None, None, None, (PlannedItem("van"), PlannedItem("guide", days=1))),
        ),
        "hints": (HINT,),
    }
    return PlannedRequest(**{**fields, **overrides})


class FakePlanner:
    def __init__(self, answer=None, raises=None):
        self.answer = answer if answer is not None else planned()
        self.raises = raises
        self.calls = []

    def plan(self, message, catalog, today):
        self.calls.append((message, catalog, today))
        if self.raises is not None:
            raise self.raises
        return self.answer


@pytest.fixture
def message(tmp_path):
    path = tmp_path / "zorro.txt"
    path.write_text(MESSAGE, encoding="utf-8")
    return path


def run(argv, *, repository=None, planner=None, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    if repository is None:
        repository = InMemoryCatalogRepository(catalog())
    kwargs.setdefault("today", lambda: date(2026, 10, 14))
    code = main(argv, repository=repository, planner=planner, out=out, err=err, **kwargs)
    return code, out.getvalue(), err.getvalue()


def plan(message, tmp_path, *extra, **kwargs):
    return run(
        ["quote", "plan", str(message), "-o", str(tmp_path / "draft.yaml"), *extra], **kwargs
    )


def test_writes_the_draft_and_prints_counts_only(message, tmp_path):
    code, out, err = plan(message, tmp_path, planner=FakePlanner())
    assert code == 0
    assert err == ""
    assert str(tmp_path / "draft.yaml") in out
    assert "options: 1" in out
    assert "services: 2" in out
    assert "hints: 3" in out  # the planner's hint plus the two owner-only reminders
    assert f"quotes quote build {tmp_path / 'draft.yaml'}" in out
    assert "needs_review: false" in out


def test_the_draft_is_marked_for_review_and_has_no_margin(message, tmp_path):
    plan(message, tmp_path, planner=FakePlanner())
    data = yaml.safe_load((tmp_path / "draft.yaml").read_text(encoding="utf-8"))
    assert data["needs_review"] is True
    assert data["pricing"]["margin_rate"] is None
    assert data["signed_by"] is None
    assert data["client"] == CLIENT
    assert [item["id"] for item in data["items"]] == ["van", "guide"]


def test_default_output_comes_from_the_message_stem(message, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out, _ = run(["quote", "plan", str(message)], planner=FakePlanner())
    assert code == 0
    assert (tmp_path / "data/private/quotes/zorro.yaml").is_file()
    assert "zorro.yaml" in out


def test_unknown_ids_become_hints_and_only_the_count_is_printed(message, tmp_path):
    answer = planned(
        options=(PlannedOption(None, None, None, (PlannedItem("van"), PlannedItem("ghost"))),),
        hints=(),
    )
    code, out, err = plan(message, tmp_path, planner=FakePlanner(answer))
    assert code == 0
    data = yaml.safe_load((tmp_path / "draft.yaml").read_text(encoding="utf-8"))
    assert any("ghost" in hint for hint in data["review_hints"])
    assert "services: 1" in out
    assert "hints: 3" in out
    assert "ghost" not in out + err


def test_several_options_are_counted(message, tmp_path):
    answer = planned(
        options=(
            PlannedOption("Option 1", None, None, (PlannedItem("van"),)),
            PlannedOption("Option 2", None, None, (PlannedItem("van"), PlannedItem("guide"))),
        ),
    )
    _, out, _ = plan(message, tmp_path, planner=FakePlanner(answer))
    assert "options: 2" in out
    assert "services: 3" in out


def test_the_planner_gets_the_message_a_price_free_view_and_today(message, tmp_path):
    fake = FakePlanner()
    plan(message, tmp_path, planner=fake)
    [(seen_message, view, seen_today)] = fake.calls
    assert seen_message == MESSAGE
    assert view.item_ids() == ("van", "guide")
    assert seen_today == date(2026, 10, 14)
    assert PRICE not in repr(view)


def test_output_never_shows_prices_margins_the_message_or_model_text(message, tmp_path):
    repo = InMemoryCatalogRepository(
        catalog(), issues=(CatalogIssue("warning", "x", "a", "secret-detail"),)
    )
    _, out, err = plan(message, tmp_path, repository=repo, planner=FakePlanner())
    for secret in (PRICE, MARGIN, MESSAGE, CLIENT, HINT, "Zorro", "secret-detail"):
        assert secret not in out + err


def test_catalog_issues_give_a_one_line_warning(message, tmp_path):
    repo = InMemoryCatalogRepository(catalog(), issues=(CatalogIssue("error", "y", "b", "d"),))
    code, _, err = plan(message, tmp_path, repository=repo, planner=FakePlanner())
    assert code == 0
    assert "warning: the catalog reported 1 issue(s)" in err


def test_existing_output_is_refused_without_force(message, tmp_path):
    output = tmp_path / "draft.yaml"
    output.write_text("old", encoding="utf-8")
    code, _, err = plan(message, tmp_path, planner=FakePlanner())
    assert code == 2
    assert "--force" in err
    assert output.read_text(encoding="utf-8") == "old"


def test_force_overwrites(message, tmp_path):
    output = tmp_path / "draft.yaml"
    output.write_text("old", encoding="utf-8")
    code, _, _ = plan(message, tmp_path, "--force", planner=FakePlanner())
    assert code == 0
    assert "needs_review" in output.read_text(encoding="utf-8")


def test_the_message_file_is_never_used_as_the_output(message):
    code, _, err = run(["quote", "plan", str(message), "-o", str(message)], planner=FakePlanner())
    assert code == 2
    assert "message" in err
    assert message.read_text(encoding="utf-8") == MESSAGE


def test_missing_message_file_exits_two(tmp_path):
    fake = FakePlanner()
    code, _, err = plan(tmp_path / "nope.txt", tmp_path, planner=fake)
    assert code == 2
    assert "nope.txt" in err
    assert fake.calls == []


@pytest.mark.parametrize("content", ["", "  \n\t\n"])
def test_blank_message_file_exits_two(message, tmp_path, content):
    message.write_text(content, encoding="utf-8")
    fake = FakePlanner()
    code, _, err = plan(message, tmp_path, planner=fake)
    assert code == 2
    assert "empty" in err
    assert fake.calls == []


def test_non_utf8_message_file_exits_two(message, tmp_path):
    message.write_bytes(b"\xff\xfe\x00bad")
    code, _, err = plan(message, tmp_path, planner=FakePlanner())
    assert code == 2
    assert str(message) in err


def test_catalog_failure_exits_two_and_the_planner_is_not_called(message, tmp_path):
    fake = FakePlanner()
    out, err = io.StringIO(), io.StringIO()
    argv = ["quote", "plan", str(message), "-o", str(tmp_path / "draft.yaml")]
    code = main(argv, env={}, planner=fake, out=out, err=err)
    assert code == 2
    assert "DATABASE_URL" in err.getvalue()
    assert fake.calls == []
    assert not (tmp_path / "draft.yaml").exists()


def test_planner_unavailable_exits_two_with_its_message(message, tmp_path):
    fake = FakePlanner(raises=PlannerUnavailable("the planner could not answer"))
    code, out, err = plan(message, tmp_path, planner=fake)
    assert code == 2
    assert "error: the planner could not answer" in err
    assert out == ""
    assert not (tmp_path / "draft.yaml").exists()


def test_a_missing_api_key_exits_two(message, tmp_path, monkeypatch):
    def no_key(env=None):
        raise MissingSetting("ANTHROPIC_API_KEY is not set")

    monkeypatch.setattr(cli, "planner_from_env", no_key)
    code, _, err = plan(message, tmp_path)
    assert code == 2
    assert "error: ANTHROPIC_API_KEY is not set" in err


def test_a_missing_llm_extra_exits_two(message, tmp_path, monkeypatch):
    def no_extra(env=None):
        raise PlannerUnavailable("the [llm] extra is not installed")

    monkeypatch.setattr(cli, "planner_from_env", no_extra)
    code, _, err = plan(message, tmp_path)
    assert code == 2
    assert "[llm]" in err


def test_the_planner_is_built_from_the_environment_only_for_plan(message, tmp_path, monkeypatch):
    def boom(env=None):
        raise AssertionError("the planner must not be built for other commands")

    monkeypatch.setattr(cli, "planner_from_env", boom)
    assert run(["catalog", "check"])[0] == 0


def test_a_fresh_draft_is_refused_by_quote_build(message, tmp_path):
    draft = tmp_path / "draft.yaml"
    plan(message, tmp_path, planner=FakePlanner())
    company = tmp_path / "company.tex"
    company.write_text("% fake company\n", encoding="utf-8")

    def never(*args, **kwargs):
        raise AssertionError("a draft must not be compiled")

    code, _, err = run(["quote", "build", str(draft), "--company", str(company)], compile=never)
    assert code == 1
    assert "still needs review" in err


# --- day texts ---

DAY_TEXT = "Generated paragraph about the first day"


class FakeDayPlanner(FakePlanner):
    def __init__(self, texts=None, raises=None, answer=None):
        super().__init__(answer)
        self.texts = texts
        self.day_raises = raises
        self.day_calls = []

    def write_days(self, days, language):
        self.day_calls.append((days, language))
        if self.day_raises is not None:
            raise self.day_raises
        return self.texts if self.texts is not None else tuple(DAY_TEXT for _ in days)


def placed() -> PlannedRequest:
    option = PlannedOption(
        None, None, None, (PlannedItem("van", on_days=(1,)),), itinerary=(PlannedDay(1, "Arrival"),)
    )
    return planned(options=(option,))


def test_day_texts_land_in_the_draft_and_only_the_count_is_printed(message, tmp_path):
    fake = FakeDayPlanner(answer=placed())
    code, out, err = plan(message, tmp_path, planner=fake)
    assert code == 0
    assert "day texts: 1" in out
    assert DAY_TEXT not in out + err
    ((days, language),) = fake.day_calls
    assert language == "en"
    assert days[0].title == "Arrival"
    draft = yaml.safe_load((tmp_path / "draft.yaml").read_text(encoding="utf-8"))
    assert draft["itinerary"] == [{"day": 1, "title": "Arrival", "text": DAY_TEXT}]


def test_a_planner_without_write_days_prints_no_day_texts(message, tmp_path):
    code, out, _ = plan(message, tmp_path, planner=FakePlanner(placed()))
    assert code == 0
    assert "day texts" not in out


def test_no_facts_means_the_writer_is_not_called(message, tmp_path):
    fake = FakeDayPlanner()
    code, out, _ = plan(message, tmp_path, planner=fake)
    assert code == 0
    assert fake.day_calls == []
    assert "day texts" not in out


def test_a_failing_day_writer_exits_two_and_writes_nothing(message, tmp_path):
    fake = FakeDayPlanner(
        raises=PlannerUnavailable("planner request failed (Boom)"), answer=placed()
    )
    code, out, err = plan(message, tmp_path, planner=fake)
    assert code == 2
    assert "planner request failed (Boom)" in err
    assert not (tmp_path / "draft.yaml").exists()


def test_a_day_writer_with_the_wrong_count_exits_two(message, tmp_path):
    fake = FakeDayPlanner(texts=("a", "b"), answer=placed())
    code, _, err = plan(message, tmp_path, planner=fake)
    assert code == 2
    assert "unexpected planner output" in err
    assert not (tmp_path / "draft.yaml").exists()
