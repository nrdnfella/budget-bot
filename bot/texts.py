"""Parsing user input and formatting replies. No I/O, so it is easy to test."""
import re

AMOUNT_RE = re.compile(r"^\s*(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(.*)$", re.S)


def parse_amount(text: str) -> tuple[float, str] | None:
    """'350 coffee' -> (350.0, 'coffee'); '1 200,50 taxi' -> (1200.5, 'taxi')."""
    m = AMOUNT_RE.match(text or "")
    if not m:
        return None
    raw, note = m.group(1), m.group(2).strip()
    # "1 200 taxi": spaces inside the number are thousands separators only when
    # every group after the first has exactly 3 digits
    parts = raw.split()
    if len(parts) > 1 and not all(len(p.split(",")[0].split(".")[0]) == 3 for p in parts[1:]):
        raw, note = parts[0], (" ".join(parts[1:]) + " " + note).strip()
    value = float(raw.replace(" ", "").replace(",", "."))
    if value <= 0:
        return None
    return value, note


def money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}{abs(x):,.0f}".replace(",", " ")


def with_tip(text: str, tip: str) -> str:
    return f"{text}\n\n💬 {tip}" if tip else text


def expense_reply(amount: float, note: str, s: dict) -> str:
    head = f"−{money(amount)}" + (f" {note}" if note else "")
    if s["left_today"] >= 0:
        line = f"Left today: {money(s['left_today'])} of {money(s['limit_today'])}"
    else:
        line = f"Over today's limit by {money(-s['left_today'])}"
    return f"{head}\n{line}\nTomorrow's limit: {money(s['limit_tomorrow'])}"


def today_reply(s: dict) -> str:
    return (f"Today's limit: {money(s['limit_today'])}\n"
            f"Spent today: {money(s['spent_today'])}\n"
            f"Left today: {money(s['left_today'])}\n"
            f"Tomorrow's limit if you stop now: {money(s['limit_tomorrow'])}")


def month_reply(s: dict) -> str:
    return (f"Free money this month: {money(s['free_month'])}\n"
            f"Spent: {money(s['spent_month'])}\n"
            f"Left: {money(s['left_month'])}\n"
            f"Days left, incl. today: {s['days_left']:.0f}")


def savings_reply(s: dict) -> str:
    lines = [f"Savings: {money(s['savings'])}"]
    if s["goal"] > 0:
        lines += [f"Goal: {money(s['goal'])}",
                  f"Left to goal: {money(s['left_to_goal'])}",
                  f"At the current rate: {s['months_to_goal']:.1f} months"]
    else:
        lines.append("No goal set yet. Put it in Settings, cell B22.")
    if s["left_month"] > 0 and s["days_left"] <= 3:
        lines.append(f"\n{money(s['left_month'])} is still unspent this month. "
                     "Moving part of it to savings now (/save) keeps it safe from the weekend.")
    return "\n".join(lines)


def _data_note(months: float) -> str:
    days = months * 30
    if days < 15:
        return f"\n(Based on {days:.0f} days of data. The forecast gets more accurate after a month.)"
    return ""


def whatif_reply(w: dict, savings_per_month: float = 0.0) -> str:
    if w["months_of_data"] == 0:
        return "No spending logged yet. Log a few weeks first, then ask again."
    if w["monthly"] == 0:
        return (f"Nothing matching '{w['label']}' in the last 90 days.\n"
                "Check the name with /forecast, or teach a keyword with /cat.")
    pct = "" if w["cut"] >= 1 else f" by {w['cut']:.0%}"
    lines = [f"{w['label']}: about {money(w['monthly'])} a month, {money(w['yearly'])} a year"
             f" ({w['times_30d']} times in the last 30 days).",
             f"Cutting it{pct} saves {money(w['saved_month'])} a month, "
             f"{money(w['saved_year'])} in a year."]
    if savings_per_month > 0:
        weeks = w["saved_year"] / savings_per_month * 4.345
        lines.append(f"That's {weeks:.1f} weeks' worth of your usual savings.")
    return "\n".join(lines) + _data_note(w["months_of_data"])


def plan_reply(p: dict, months_of_data: float) -> str:
    head = (f"Goal: {money(p['target'])} in {p['months']} months, "
            f"so {money(p['needed'])} a month.\n"
            f"You already save {money(p['saving'])} a month.")
    if p["gap"] == 0:
        return (f"{head}\nNo cuts needed: your current savings reach it in "
                f"{p['months_at_current']:.1f} months.")
    lines = [head, f"Extra needed: {money(p['gap'])} a month.", ""]
    if not p["cuts"]:
        lines.append("No spending logged yet, so there's nothing to suggest cutting. "
                     "Log a few weeks first.")
        return "\n".join(lines)
    lines.append("Suggested cuts:")
    for c in p["cuts"]:
        lines.append(f"• {c['category']}: −{money(c['cut'])} a month "
                     f"({c['pct']:.0%} of {money(c['monthly'])})")
    if p["uncovered"] > 0:
        lines.append(f"\nEven halving every category leaves {money(p['uncovered'])} a month short. "
                     f"Realistic timeline: {p['months_with_max_cuts']:.1f} months.")
    lines.append("\nRent, family and other fixed costs are not touched.")
    return "\n".join(lines) + _data_note(months_of_data)


def forecast_reply(by_cat: dict, months: float) -> str:
    if not by_cat:
        return "No spending logged yet."
    total = sum(by_cat.values())
    lines = ["Average spending per month by category:"]
    for cat, m in list(by_cat.items())[:10]:
        lines.append(f"• {cat}: {money(m)} ({m / total:.0%}), {money(m * 12)} a year")
    return "\n".join(lines) + _data_note(months)


HELP = """Send an amount to log spending:
  350 coffee
  1 200 taxi

/today: today's limit and what's left
/month: this month so far
/savings: savings balance and goal
/save 10000 [note]: money into savings
/take 5000 [note]: money out of savings
/earlier 40000: spending earlier this month, before the bot
/undo: remove the last expense

Forecasts:
/forecast: spending by category, per month and per year
/whatif coffee: how much giving up coffee saves in a year
/whatif taxi 50%: the same for cutting taxi by half
/plan 300000 12: what to cut to save 300 000 in 12 months
/cat starbucks Coffee: teach a keyword → category

/teach <situation> <tip>: teach the bot a new tip
  situations: overspent, on_track, saving, withdraw, payday, morning, forecast
/tip [situation]: get a tip now
/retrain: rebuild the budget-jester model from the Advice tab
/model: show or switch the model (base / jester)"""
