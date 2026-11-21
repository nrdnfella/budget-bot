"""Telegram budget bot: logs spending to the Budget Google Sheet, reports the daily
limit, and adds a funny tip from a local Ollama model or the Advice tab."""
import asyncio
import datetime as dt
import functools
import json
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (Application, CommandHandler, ContextTypes, MessageHandler,
                          filters)

from advice import Adviser, situation_for
from forecast import EARLIER, categorize, monthly_by_category, plan, what_if
from jester import JESTER_NAME, create_request
from sheet import SITUATIONS, Budget, to_serial
from texts import (HELP, expense_reply, forecast_reply, money, month_reply,
                   parse_amount, plan_reply, savings_reply, today_reply, whatif_reply,
                   with_tip)

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    level=logging.INFO)
log = logging.getLogger("budget-bot")

TZ = ZoneInfo(os.environ.get("TZ", "Europe/Moscow"))
DATA = Path(os.environ.get("DATA_DIR", "data"))
OWNER_FILE = DATA / "owner.json"

budget = Budget(os.environ.get("GOOGLE_CREDENTIALS", "secrets/service-account.json"),
                os.environ["SPREADSHEET_ID"])
BASE_MODEL = os.environ.get("OLLAMA_BASE_MODEL", os.environ.get("OLLAMA_MODEL", "qwen2.5:3b"))
MODEL_FILE = DATA / "model.txt"  # which model is active: base or budget-jester


def active_model() -> str:
    if MODEL_FILE.exists() and MODEL_FILE.read_text().strip():
        return MODEL_FILE.read_text().strip()
    return BASE_MODEL


def set_active_model(name: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    MODEL_FILE.write_text(name)
    adviser.model = name


adviser = Adviser(os.environ.get("OLLAMA_URL"), active_model())


def now() -> dt.datetime:
    return dt.datetime.now(TZ)


def run(fn, *args):
    """gspread is blocking; keep the event loop free."""
    return asyncio.to_thread(fn, *args)


# ---- owner lock ---------------------------------------------------------
def get_owner() -> int | None:
    if os.environ.get("OWNER_CHAT_ID"):
        return int(os.environ["OWNER_CHAT_ID"])
    if OWNER_FILE.exists():
        return json.loads(OWNER_FILE.read_text())["chat_id"]
    return None


def owner_only(handler):
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        owner = get_owner()
        if owner is None:  # first chat to write claims the bot
            DATA.mkdir(parents=True, exist_ok=True)
            OWNER_FILE.write_text(json.dumps({"chat_id": chat_id}))
            log.info("Owner set to chat %s", chat_id)
            owner = chat_id
        if chat_id != owner:
            return
        return await handler(update, context)
    return wrapper


async def tip_for(event: str, status: dict, is_payday: bool = False) -> str:
    situation = situation_for(event, status, is_payday)
    examples = await run(budget.tips, situation)
    return await adviser.tip(situation, status, examples)


# ---- handlers -----------------------------------------------------------
@owner_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Budget bot is ready.\n\n" + HELP)


@owner_only
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP)


@owner_only
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed = parse_amount(update.message.text)
    if not parsed:
        await update.message.reply_text("Send an amount, e.g. `350 coffee`. /help for commands.",
                                        parse_mode="Markdown")
        return
    amount, note = parsed
    category = categorize(note, await run(budget.category_rules))
    await run(budget.add_expense, amount, note, now(), category)
    s = await run(budget.status)
    reply = expense_reply(amount, note, s) + f"\nCategory: {category}"
    await update.message.reply_text(with_tip(reply, await tip_for("expense", s)))


@owner_only
async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(today_reply(await run(budget.status)))


@owner_only
async def month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(month_reply(await run(budget.status)))


@owner_only
async def savings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(savings_reply(await run(budget.status)))


async def _savings_move(update: Update, context, sign: int, event: str):
    parsed = parse_amount(" ".join(context.args))
    if not parsed:
        await update.message.reply_text(f"Usage: /{'save' if sign > 0 else 'take'} 10000 [note]")
        return
    amount, note = parsed
    await run(budget.add_saving, sign * amount, note, now())
    s = await run(budget.status)
    verb = "Saved" if sign > 0 else "Taken from savings:"
    await update.message.reply_text(with_tip(
        f"{verb} {money(amount)}\nSavings now: {money(s['savings'])}",
        await tip_for(event, s)))


@owner_only
async def save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _savings_move(update, context, +1, "saving")


@owner_only
async def take(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _savings_move(update, context, -1, "withdraw")


@owner_only
async def earlier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed = parse_amount(" ".join(context.args))
    if not parsed:
        await update.message.reply_text("Usage: /earlier 40000 (what you spent this month before the bot)")
        return
    amount, _ = parsed
    start_of_month = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    await run(budget.add_expense, amount, "Spent earlier this month", start_of_month, EARLIER)
    await update.message.reply_text("Recorded.\n\n" + today_reply(await run(budget.status)))


@owner_only
async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = await run(budget.undo_expense)
    if not row:
        await update.message.reply_text("Nothing to undo.")
        return
    s = await run(budget.status)
    await update.message.reply_text(f"Removed: {' | '.join(row)}\n\n" + today_reply(s))


async def forecast_tip(s: dict | None = None) -> str:
    s = s or await run(budget.status)
    examples = await run(budget.tips, "forecast")
    return await adviser.tip("forecast", s, examples)


@owner_only
async def forecast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await run(budget.expense_rows)
    by_cat, months = monthly_by_category(rows, to_serial(now()))
    await update.message.reply_text(forecast_reply(by_cat, months))


@owner_only
async def whatif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = list(context.args)
    cut = 1.0
    if args and args[-1].endswith("%"):
        try:
            cut = max(0.0, min(1.0, float(args.pop().rstrip("%").replace(",", ".")) / 100))
        except ValueError:
            pass
    if not args:
        await update.message.reply_text("Usage: /whatif coffee  or  /whatif taxi 50%")
        return
    rows = await run(budget.expense_rows)
    rules = await run(budget.category_rules)
    w = what_if(" ".join(args), rows, rules, to_serial(now()), cut)
    text = whatif_reply(w, await run(budget.savings_per_month))
    tip_text = await forecast_tip() if w["monthly"] > 0 else ""
    await update.message.reply_text(with_tip(text, tip_text))


@owner_only
async def plan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target = parse_amount(context.args[0])[0]
        months = int(context.args[1]) if len(context.args) > 1 else 12
        if months <= 0:
            raise ValueError
    except (IndexError, TypeError, ValueError):
        await update.message.reply_text("Usage: /plan 300000 12  (amount, months; default 12)")
        return
    rows = await run(budget.expense_rows)
    by_cat, data_months = monthly_by_category(rows, to_serial(now()))
    p = plan(target, months, await run(budget.savings_per_month), by_cat)
    tip_text = await forecast_tip() if p["cuts"] else ""
    await update.message.reply_text(with_tip(plan_reply(p, data_months), tip_text))


@owner_only
async def cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /cat starbucks Coffee\n"
                                        "Expenses whose note contains the keyword get that category.")
        return
    keyword, category = context.args[0], " ".join(context.args[1:])
    await run(budget.add_category, keyword, category)
    await update.message.reply_text(f"From now on, '{keyword}' → {category}. "
                                    "Earlier entries keep their category; you can fix them in the sheet.")


@owner_only
async def retrain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tips = await run(budget.all_tips)
    body = create_request(tips, BASE_MODEL)
    pairs = len(body["messages"]) // 2
    await update.message.reply_text(f"Building {JESTER_NAME} from {pairs} tips on {BASE_MODEL}…")
    try:
        await adviser.create_model(body)
    except Exception as e:
        log.exception("retrain failed")
        await update.message.reply_text(f"Couldn't build the model: {e}\n"
                                        f"Still using {adviser.model}.")
        return
    set_active_model(JESTER_NAME)
    s = await run(budget.status)
    sample = await adviser.tip("on_track", s, await run(budget.tips, "on_track"))
    await update.message.reply_text(f"Done. Now using {JESTER_NAME}.\nSample: {sample}\n\n"
                                    "Back to the plain model: /model base")


@owner_only
async def model_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = context.args[0].lower() if context.args else ""
    if choice in ("base", "jester"):
        set_active_model(BASE_MODEL if choice == "base" else JESTER_NAME)
    await update.message.reply_text(f"Model: {adviser.model}\n"
                                    "Switch: /model base  or  /model jester (after /retrain)")


@owner_only
async def teach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2 or context.args[0] not in SITUATIONS:
        await update.message.reply_text("Usage: /teach <situation> <tip>\nSituations: "
                                        + ", ".join(SITUATIONS))
        return
    situation, text = context.args[0], " ".join(context.args[1:])
    author = update.effective_user.first_name or "me"
    await run(budget.add_tip, situation, text, author)
    count = len(await run(budget.tips, situation))
    await update.message.reply_text(f"Learned. {count} tips for '{situation}' now.")


@owner_only
async def tip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    situation = context.args[0] if context.args and context.args[0] in SITUATIONS else "on_track"
    s = await run(budget.status)
    examples = await run(budget.tips, situation)
    await update.message.reply_text(await adviser.tip(situation, s, examples) or "No tips yet. Use /teach.")


async def morning(context: ContextTypes.DEFAULT_TYPE):
    owner = get_owner()
    if owner is None:
        return
    s = await run(budget.status)
    is_payday = now().day in await run(budget.paydays)
    text = f"Good morning. Today's limit: {money(s['limit_today'])}"
    await context.bot.send_message(owner, with_tip(text, await tip_for("morning", s, is_payday)))


def main():
    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    for name, fn in [("start", start), ("help", help_cmd), ("today", today), ("month", month),
                     ("savings", savings), ("save", save), ("take", take), ("earlier", earlier),
                     ("undo", undo), ("teach", teach), ("tip", tip),
                     ("forecast", forecast_cmd), ("whatif", whatif), ("plan", plan_cmd),
                     ("cat", cat), ("retrain", retrain), ("model", model_cmd)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    hour = budget.morning_hour()
    app.job_queue.run_daily(morning, time=dt.time(hour=hour, tzinfo=TZ))
    log.info("Starting; morning message at %02d:00 %s", hour, TZ)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
