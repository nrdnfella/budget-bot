import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))

from forecast import Row, categorize, monthly_by_category, plan, what_if  # noqa: E402
from texts import plan_reply, whatif_reply  # noqa: E402

RULES = [("coffee", "Coffee"), ("кофе", "Coffee"), ("taxi", "Taxi"), ("wb", "Shopping")]
TODAY = 46347.0  # 21.11.2026


def rows_30_days():
    """30 days of data: coffee 300 daily, taxi 1000 every 5 days, an Earlier lump sum."""
    out = [Row(TODAY - 29 - 0.5, 50000, "Spent earlier", "Earlier")]
    for d in range(30):
        out.append(Row(TODAY - d + 0.4, 300, "coffee latte", "Coffee"))
        if d % 5 == 0:
            out.append(Row(TODAY - d + 0.6, 1000, "taxi home", "Taxi"))
    return out


def test_categorize():
    assert categorize("Coffee at work", RULES) == "Coffee"
    assert categorize("кофейня у метро", RULES) == "Coffee"   # word-prefix match
    assert categorize("cobweb remover", RULES) == "Cobweb"    # 'wb' inside a word doesn't match
    assert categorize("wb order", RULES) == "Shopping"
    assert categorize("", RULES) == "Other"


def test_monthly_by_category_excludes_earlier():
    by_cat, months = monthly_by_category(rows_30_days(), TODAY)
    assert abs(months - 1.0) < 0.05
    assert "Earlier" not in by_cat
    assert list(by_cat) == ["Coffee", "Taxi"]          # sorted, biggest first
    assert abs(by_cat["Coffee"] - 9000 / months) < 1
    assert abs(by_cat["Taxi"] - 6000 / months) < 1


def test_what_if_by_category_keyword_and_note():
    rows = rows_30_days()
    w = what_if("coffee", rows, RULES, TODAY)
    assert w["label"] == "Coffee" and abs(w["yearly"] - 12 * 9000 / w["months_of_data"]) < 1
    w_ru = what_if("кофе", rows, RULES, TODAY)             # mapped through the rules
    assert w_ru["label"] == "Coffee" and w_ru["monthly"] == w["monthly"]
    half = what_if("taxi", rows, RULES, TODAY, cut=0.5)
    assert abs(half["saved_month"] - half["monthly"] / 2) < 1e-6
    by_note = what_if("latte", rows, RULES, TODAY)         # free text in notes
    assert by_note["monthly"] == w["monthly"]
    assert what_if("yacht", rows, RULES, TODAY)["monthly"] == 0


def test_plan_no_cuts_needed():
    p = plan(300000, 12, 65180, {"Coffee": 9000})
    assert p["gap"] == 0 and not p["cuts"]
    assert "No cuts needed" in plan_reply(p, 1.0)


def test_plan_greedy_cuts():
    p = plan(120000, 12, 5000, {"Eating out": 8000, "Coffee": 4000, "Taxi": 2000})
    assert p["gap"] == 5000
    assert p["cuts"][0] == {"category": "Eating out", "monthly": 8000, "cut": 4000, "pct": 0.5}
    assert p["cuts"][1]["category"] == "Coffee" and p["cuts"][1]["cut"] == 1000
    assert p["uncovered"] == 0


def test_plan_not_reachable():
    p = plan(1_000_000, 6, 10000, {"Coffee": 4000})
    assert p["uncovered"] > 0
    assert "short" in plan_reply(p, 1.0)


def test_whatif_reply_text():
    w = what_if("coffee", rows_30_days(), RULES, TODAY)
    text = whatif_reply(w, 65180)
    assert "Coffee: about" in text and "a year" in text and "weeks' worth" in text
