"""Access to the Budget Google Sheet. All money maths lives in the sheet's formulas;
this module only writes rows and reads the results from the Today tab."""
import datetime as dt
import random

import gspread

from forecast import Row

EPOCH = dt.datetime(1899, 12, 30)

# Row order of Today!B3:B19 (None = blank spacer row)
TODAY_KEYS = [
    "date", "month_start", "days_in_month", "days_left", "free_month",
    "spent_before", "limit_today", "spent_today", "left_today", "spent_month",
    "left_month", "limit_tomorrow", None, "savings", "goal", "left_to_goal",
    "months_to_goal",
]

SITUATIONS = ["overspent", "on_track", "saving", "withdraw", "payday", "morning", "forecast"]


def to_serial(t: dt.datetime) -> float:
    """Datetime -> Sheets date serial number (days since 1899-12-30)."""
    t = t.replace(tzinfo=None)
    return (t - EPOCH).total_seconds() / 86400


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class Budget:
    def __init__(self, creds_path: str, spreadsheet_id: str):
        gc = gspread.service_account(filename=creds_path)
        self.ss = gc.open_by_key(spreadsheet_id)
        self.today_ws = self.ss.worksheet("Today")
        self.settings_ws = self.ss.worksheet("Settings")
        self.expenses_ws = self.ss.worksheet("Expenses")
        self.savings_ws = self.ss.worksheet("Savings")
        self.advice_ws = self.ss.worksheet("Advice")
        self.categories_ws = self.ss.worksheet("Categories")

    # ---- reading -------------------------------------------------------
    def status(self) -> dict:
        rows = self.today_ws.get("B3:B19", value_render_option="UNFORMATTED_VALUE")
        rows = list(rows) + [[]] * (len(TODAY_KEYS) - len(rows))
        return {k: _num(r[0] if r else 0) for k, r in zip(TODAY_KEYS, rows) if k}

    def paydays(self) -> list[int]:
        rows = self.settings_ws.get("C4:C5", value_render_option="UNFORMATTED_VALUE")
        return [int(_num(r[0])) for r in rows if r]

    def savings_per_month(self) -> float:
        rows = self.settings_ws.get("B19", value_render_option="UNFORMATTED_VALUE")
        return _num(rows[0][0]) if rows and rows[0] else 0.0

    def morning_hour(self, default: int = 9) -> int:
        rows = self.settings_ws.get("B23", value_render_option="UNFORMATTED_VALUE")
        h = int(_num(rows[0][0])) if rows and rows[0] else default
        return h if 0 <= h <= 23 else default

    def tips(self, situation: str) -> list[str]:
        rows = self.advice_ws.get("A2:B", value_render_option="UNFORMATTED_VALUE")
        return [r[1] for r in rows if len(r) > 1 and r[0] == situation and str(r[1]).strip()]

    def random_tip(self, situation: str) -> str:
        tips = self.tips(situation)
        return random.choice(tips) if tips else ""

    def category_rules(self) -> list[tuple[str, str]]:
        rows = self.categories_ws.get("A2:B", value_render_option="UNFORMATTED_VALUE")
        return [(str(r[0]).strip().lower(), str(r[1]).strip())
                for r in rows if len(r) > 1 and str(r[0]).strip() and str(r[1]).strip()]

    def expense_rows(self) -> list[Row]:
        rows = self.expenses_ws.get("A2:D", value_render_option="UNFORMATTED_VALUE")
        out = []
        for r in rows:
            r = list(r) + [""] * (4 - len(r))
            if r[0] == "" or r[1] == "":
                continue
            out.append(Row(_num(r[0]), _num(r[1]), str(r[2]), str(r[3]) or "Other"))
        return out

    # ---- writing -------------------------------------------------------
    def add_expense(self, amount: float, note: str, when: dt.datetime,
                    category: str = "Other") -> None:
        self.expenses_ws.append_row([to_serial(when), amount, note, category],
                                    value_input_option="RAW", table_range="A1")

    def add_category(self, keyword: str, category: str) -> None:
        self.categories_ws.append_row([keyword.lower(), category],
                                      value_input_option="RAW", table_range="A1")

    def undo_expense(self) -> list[str] | None:
        n = len(self.expenses_ws.col_values(1))
        if n <= 1:
            return None
        row = self.expenses_ws.row_values(n)
        self.expenses_ws.delete_rows(n)
        return row

    def add_saving(self, amount: float, note: str, when: dt.datetime) -> None:
        day = when.replace(hour=0, minute=0, second=0, microsecond=0)
        self.savings_ws.append_row([to_serial(day), amount, note],
                                   value_input_option="RAW", table_range="A1")

    def add_tip(self, situation: str, text: str, author: str) -> None:
        self.advice_ws.append_row([situation, text, author],
                                  value_input_option="RAW", table_range="A1")
