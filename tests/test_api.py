# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

from contextlib import contextmanager
from importlib.util import find_spec
from types import SimpleNamespace

import pytest

from rigoraudit import api, settings

# ask() reads anthropic's error types, even with a stand-in client
needs_anthropic = pytest.mark.skipif(
    find_spec("anthropic") is None, reason="needs the api option: uv sync --extra api"
)


class Client:
    """Stands in for Anthropic's client: answers with ``stop`` and ``text``."""

    def __init__(self, stop="end_turn", text="{}"):
        self.sent = []
        self.stop, self.text = stop, text
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    @contextmanager
    def stream(self, **request):
        self.sent.append(request)
        blocks = [
            SimpleNamespace(type="thinking"),
            SimpleNamespace(type="text", text=self.text),
        ]
        message = SimpleNamespace(stop_reason=self.stop, content=blocks)
        yield SimpleNamespace(get_final_message=lambda: message)


@needs_anthropic
def test_a_conversation_keeps_every_turn():
    client = Client(text='{"a": 1}')
    talk = api.Conversation("claude-opus-5-5", client=client)
    assert talk.ask("task") == '{"a": 1}'
    talk.ask("problems")
    request = client.sent[-1]
    assert request["model"] == "claude-opus-5-5" and request["fallbacks"] == "default"
    assert [m["role"] for m in request["messages"]] == ["user", "assistant"] * 2


@needs_anthropic
@pytest.mark.parametrize(
    ("stop", "why"), [("refusal", "declined"), ("max_tokens", "cut off")]
)
def test_a_reply_that_cannot_be_used_says_why(stop, why):
    talk = api.Conversation("claude-opus-5-5", client=Client(stop=stop))
    with pytest.raises(api.Unavailable, match=why):
        talk.ask("task")


def test_the_manifest_names_the_model(tmp_path):
    (tmp_path / "audit.yaml").write_text(
        "materials:\n  manuscript:\n    path: paper.pdf\n"
        "settings:\n  assistant:\n    model: claude-sonnet-5-5\n",
        encoding="utf-8",
    )
    assert settings.load(tmp_path).model == "claude-sonnet-5-5"
    (tmp_path / "audit.yaml").write_text(
        "materials:\n  manuscript:\n    path: paper.pdf\n", encoding="utf-8"
    )
    assert settings.load(tmp_path).model == settings.MODEL
