import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))

from advice import Adviser, build_prompt, clean, situation_for  # noqa: E402
from sheet import to_serial  # noqa: E402
from texts import expense_reply, money, parse_amount, savings_reply  # noqa: E402
import datetime as dt  # noqa: E402

S = {"left_today": 4367, "limit_today": 4717, "limit_tomorrow": 4800, "left_month": 100000,
     "spent_today": 350, "free_month": 146218, "spent_month": 46218, "days_left": 10,
     "savings": 128925, "goal": 0, "left_to_goal": 0, "months_to_goal": 0}


def test_parse_amount():
    assert parse_amount("350 coffee") == (350.0, "coffee")
    assert parse_amount("350") == (350.0, "")
    assert parse_amount("350,50 кофе") == (350.5, "кофе")
    assert parse_amount("1 200 taxi") == (1200.0, "taxi")
    assert parse_amount("1 200,5 taxi") == (1200.5, "taxi")
    assert parse_amount("12 500 000") == (12500000.0, "")
    assert parse_amount("350 2 coffees") == (350.0, "2 coffees")
    assert parse_amount("coffee") is None
    assert parse_amount("0 nothing") is None


def test_money():
    assert money(146218.4) == "146 218"
    assert money(-520) == "-520"


def test_situation():
    assert situation_for("expense", {"left_today": -1}) == "overspent"
    assert situation_for("expense", {"left_today": 0}) == "on_track"
    assert situation_for("morning", {}, is_payday=True) == "payday"
    assert situation_for("morning", {}) == "morning"
    assert situation_for("saving", {}) == "saving"


def test_replies():
    assert "Left today: 4 367 of 4 717" in expense_reply(350, "coffee", S)
    assert "Over today's limit by 200" in expense_reply(350, "", {**S, "left_today": -200})
    assert "Settings, cell B22" in savings_reply(S)
    assert "months" in savings_reply({**S, "goal": 3000000, "left_to_goal": 2871075,
                                      "months_to_goal": 44.0})


def test_serial():
    assert to_serial(dt.datetime(2026, 11, 21)) == 46347.0
    assert abs(to_serial(dt.datetime(2026, 11, 21, 12)) - 46347.5) < 1e-9


def test_clean_and_prompt():
    assert clean('1. "Your wallet needs a nap."\nextra') == "Your wallet needs a nap."
    p = build_prompt("overspent", S, ["tip one", "tip two"])
    assert "- tip one" in p and "over today's spending limit" in p


def test_adviser_falls_back_to_table(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    a = Adviser("http://ollama:11434", "m")
    assert asyncio.run(a.tip("on_track", S, ["only tip"])) == "only tip"
    assert asyncio.run(Adviser(None, "m").tip("on_track", S, [])) == ""


def test_adviser_uses_model(monkeypatch):
    async def fake_post(self, url, json):
        assert url.endswith("/api/generate") and json["stream"] is False
        return httpx.Response(200, json={"response": '"Fresh model joke."'},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    assert asyncio.run(Adviser("http://x", "m").tip("on_track", S, ["t"])) == "Fresh model joke."
