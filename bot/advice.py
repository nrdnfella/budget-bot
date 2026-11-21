"""Funny tips: a local Ollama model writes a new line in the style of the Advice tab,
and a random line from the tab is used when the model is off or unreachable."""
import logging
import random
import re

import httpx

log = logging.getLogger(__name__)

DESCRIPTIONS = {
    "overspent": "the user just went over today's spending limit",
    "on_track": "the user spent something but is still within today's limit",
    "saving": "the user just put money into savings",
    "withdraw": "the user just took money out of savings",
    "payday": "it is payday morning",
    "morning": "it is the morning daily-limit reminder",
    "forecast": "the user is checking how much they could save by cutting some spending",
}


def situation_for(event: str, status: dict, is_payday: bool = False) -> str:
    if event == "expense":
        return "overspent" if status.get("left_today", 0) < 0 else "on_track"
    if event == "morning":
        return "payday" if is_payday else "morning"
    return event  # "saving" / "withdraw"


def build_prompt(situation: str, status: dict, examples: list[str]) -> str:
    shots = "\n".join(f"- {e}" for e in examples[:12]) or "- (no examples yet)"
    return (
        "You write one short, funny line of money advice for a personal budget bot.\n"
        f"Situation: {DESCRIPTIONS.get(situation, situation)}.\n"
        f"Numbers (RUB): left today {status.get('left_today', 0):.0f}, "
        f"today's limit {status.get('limit_today', 0):.0f}, "
        f"left this month {status.get('left_month', 0):.0f}.\n"
        "Match the tone, language and length of these examples:\n"
        f"{shots}\n"
        "Reply with the new line only: no quotes, no explanation, under 25 words."
    )


def clean(text: str) -> str:
    line = next((l for l in text.strip().splitlines() if l.strip()), "")
    line = re.sub(r"^\s*[-*\d.)]+\s*", "", line)  # drop list markers
    return line.strip().strip('"«»“”').strip()


class Adviser:
    def __init__(self, ollama_url: str | None, model: str, timeout: float = 25.0):
        self.url = (ollama_url or "").rstrip("/")
        self.model = model
        self.timeout = timeout

    async def tip(self, situation: str, status: dict, examples: list[str]) -> str:
        if self.url:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    r = await client.post(f"{self.url}/api/generate", json={
                        "model": self.model,
                        "prompt": build_prompt(situation, status, examples),
                        "stream": False,
                        "options": {"temperature": 0.9, "num_predict": 80},
                    })
                    r.raise_for_status()
                    line = clean(r.json().get("response", ""))
                    if line:
                        return line
            except Exception as e:  # model down, slow or not pulled: use the table
                log.warning("Ollama unavailable, using table tip: %s", e)
        return random.choice(examples) if examples else ""
