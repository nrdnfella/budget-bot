"""Builds the 'budget-jester' model: a base model with your persona and the Advice tab
baked in as example dialogues (Ollama Modelfile, level 2 in the README).

Used by the bot's /retrain command. Can also be run by hand to print a Modelfile:
    python jester.py > Modelfile && ollama create budget-jester -f Modelfile
"""
import json
import os
from collections import defaultdict

from advice import DESCRIPTIONS

JESTER_NAME = "budget-jester"
PER_SITUATION = 6  # examples per situation; keeps the context small for a 3B model

SYSTEM = (
    "You are the budget jester: a personal budget bot that answers with one short, funny "
    "line of money advice. You tease kindly, never shame. Mention the situation, keep it "
    "under 25 words, no quotes, no hashtags, no emoji. Reply in the same language as the "
    "examples you were shown."
)

PARAMETERS = {"temperature": 0.9, "top_p": 0.9, "num_predict": 80, "repeat_penalty": 1.15}


def example_request(situation: str) -> str:
    return f"Situation: {DESCRIPTIONS.get(situation, situation)}. Give me one line."


def pick_examples(tips: list[tuple[str, str]], per_situation: int = PER_SITUATION):
    """Newest tips first: what you teach recently matters most."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for situation, tip in reversed(tips):
        if tip.strip() and len(grouped[situation]) < per_situation:
            grouped[situation].append(tip.strip())
    return grouped


def create_request(tips: list[tuple[str, str]], base_model: str, name: str = JESTER_NAME) -> dict:
    """Body for Ollama POST /api/create."""
    messages = []
    for situation, examples in pick_examples(tips).items():
        for tip in examples:
            messages.append({"role": "user", "content": example_request(situation)})
            messages.append({"role": "assistant", "content": tip})
    return {"model": name, "from": base_model, "system": SYSTEM,
            "parameters": PARAMETERS, "messages": messages, "stream": False}


def _q(text: str) -> str:
    return '"""' + text.replace('"""', "'''") + '"""'


def modelfile(tips: list[tuple[str, str]], base_model: str) -> str:
    """The same model as a Modelfile, for reading or for `ollama create` by hand."""
    req = create_request(tips, base_model)
    lines = [f"FROM {base_model}", f"SYSTEM {_q(SYSTEM)}"]
    lines += [f"PARAMETER {k} {v}" for k, v in PARAMETERS.items()]
    lines += [f"MESSAGE {m['role']} {_q(m['content'])}" for m in req["messages"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    from sheet import Budget
    budget = Budget(os.environ.get("GOOGLE_CREDENTIALS", "secrets/service-account.json"),
                    os.environ["SPREADSHEET_ID"])
    base = os.environ.get("OLLAMA_BASE_MODEL", os.environ.get("OLLAMA_MODEL", "qwen2.5:3b"))
    if os.environ.get("FORMAT") == "json":
        print(json.dumps(create_request(budget.all_tips(), base), ensure_ascii=False, indent=2))
    else:
        print(modelfile(budget.all_tips(), base), end="")
