import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))

from advice import Adviser  # noqa: E402
from jester import JESTER_NAME, create_request, modelfile, pick_examples  # noqa: E402

TIPS = [("on_track", f"old {i}") for i in range(10)] + [("overspent", 'Say "no" to the cart.')]


def test_pick_examples_newest_first_and_capped():
    g = pick_examples(TIPS, per_situation=3)
    assert g["on_track"] == ["old 9", "old 8", "old 7"]
    assert g["overspent"] == ['Say "no" to the cart.']


def test_create_request_shape():
    body = create_request(TIPS, "qwen2.5:3b")
    assert body["model"] == JESTER_NAME and body["from"] == "qwen2.5:3b"
    assert body["stream"] is False and "budget jester" in body["system"]
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant"] * (len(roles) // 2)
    assert {"role": "assistant", "content": "old 9"} in body["messages"]


def test_modelfile_text():
    text = modelfile(TIPS, "qwen2.5:3b")
    assert text.startswith("FROM qwen2.5:3b\nSYSTEM \"\"\"")
    assert "PARAMETER temperature 0.9" in text
    assert 'MESSAGE assistant """Say "no" to the cart."""' in text


def test_create_model_success_and_failure(monkeypatch):
    async def ok(self, url, json):
        assert url.endswith("/api/create") and json["model"] == JESTER_NAME
        return httpx.Response(200, json={"status": "success"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", ok)
    asyncio.run(Adviser("http://x", "m").create_model(create_request(TIPS, "b")))

    async def bad(self, url, json):
        return httpx.Response(200, json={"status": "pulling manifest"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", bad)
    with pytest.raises(RuntimeError):
        asyncio.run(Adviser("http://x", "m").create_model(create_request(TIPS, "b")))
    with pytest.raises(RuntimeError):
        asyncio.run(Adviser(None, "m").create_model({}))
