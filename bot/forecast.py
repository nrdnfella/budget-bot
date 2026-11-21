"""Forecasts from the expense log: 'what if I cut X' and 'what to cut to save N'.
Pure functions over rows, so they are easy to test."""
import re
from dataclasses import dataclass

WINDOW_DAYS = 90
EARLIER = "Earlier"  # lump sums from /earlier; not real spending habits


@dataclass
class Row:
    date: float      # Sheets serial date
    amount: float
    note: str
    category: str


def _match(keyword: str, text: str) -> bool:
    """Keyword matches the start of a word: 'кофе' matches 'кофейня', 'wb' doesn't match 'cobweb'."""
    return bool(re.search(r"(?<!\w)" + re.escape(keyword.lower()), text.lower()))


def categorize(note: str, rules: list[tuple[str, str]]) -> str:
    for keyword, category in rules:
        if keyword and _match(keyword, note):
            return category
    words = note.split()
    return words[0].capitalize() if words else "Other"


def history(rows: list[Row], today: float, window: int = WINDOW_DAYS):
    """Rows in the window (without Earlier) and how many months of data they cover."""
    real = [r for r in rows if r.category != EARLIER and r.amount > 0]
    if not real:
        return [], 0.0
    first = min(r.date for r in real)
    days = min(window, max(1.0, today - first + 1))
    recent = [r for r in real if r.date >= today - window]
    return recent, days / 30


def monthly_by_category(rows: list[Row], today: float) -> tuple[dict[str, float], float]:
    recent, months = history(rows, today)
    totals: dict[str, float] = {}
    for r in recent:
        totals[r.category] = totals.get(r.category, 0) + r.amount
    if months == 0:
        return {}, 0.0
    by_cat = {c: t / months for c, t in totals.items()}
    return dict(sorted(by_cat.items(), key=lambda kv: -kv[1])), months


def what_if(query: str, rows: list[Row], rules: list[tuple[str, str]], today: float,
            cut: float = 1.0) -> dict:
    """How much cutting a category (or anything whose note matches) saves."""
    recent, months = history(rows, today)
    cats = {r.category.lower(): r.category for r in recent}
    q = query.strip()
    if q.lower() in cats:
        label = cats[q.lower()]
        picked = [r for r in recent if r.category == label]
    else:
        mapped = categorize(q, rules)
        if mapped.lower() in cats and mapped.lower() != q.lower():
            label = cats[mapped.lower()]
            picked = [r for r in recent if r.category == label]
        else:
            label = q
            picked = [r for r in recent if _match(q, r.note)]
    total = sum(r.amount for r in picked)
    monthly = total / months if months else 0.0
    last30 = [r for r in picked if r.date >= today - 30]
    return {"label": label, "monthly": monthly, "yearly": monthly * 12, "cut": cut,
            "saved_month": monthly * cut, "saved_year": monthly * 12 * cut,
            "times_30d": len(last30), "months_of_data": months}


def plan(target: float, months: int, saving_per_month: float, by_cat: dict[str, float],
         max_cut: float = 0.5) -> dict:
    """Greedy plan: cut the biggest categories (up to max_cut each) until the gap is covered."""
    needed = target / months if months else target
    gap = max(0.0, needed - saving_per_month)
    cuts, remaining = [], gap
    for cat, monthly in by_cat.items():
        if remaining <= 0:
            break
        amount = min(monthly * max_cut, remaining)
        if amount <= 0:
            continue
        cuts.append({"category": cat, "monthly": monthly, "cut": amount,
                     "pct": amount / monthly})
        remaining -= amount
    max_possible = saving_per_month + sum(m * max_cut for m in by_cat.values())
    return {"target": target, "months": months, "needed": needed, "saving": saving_per_month,
            "gap": gap, "cuts": cuts, "uncovered": max(0.0, remaining),
            "months_at_current": target / saving_per_month if saving_per_month else 0.0,
            "months_with_max_cuts": target / max_possible if max_possible else 0.0}
