# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Send a task to Claude with the user's own API key (decision 0011, item 3).

The guide can hand each task to a model itself instead of asking the user
to paste it into a chat. Each task is one conversation: the handoff's text,
then, for a reply with problems, the same block a user would paste back.
The library this needs is optional: ``miragold[api]``. The key is read
the way Anthropic's library reads it, from ``ANTHROPIC_API_KEY`` or a
saved login.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_TOKENS = 64_000
INSTALL = (
    "API mode needs Anthropic's library. Install the tool with it: from the "
    "tool's folder, run uv tool install --editable '.[api]'"
)


class Unavailable(Exception):
    """The model could not be asked, or would not answer; the message says why
    in plain words."""


@dataclass
class Conversation:
    """One task's conversation with ``model``."""

    model: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    client: Any = None

    def __post_init__(self) -> None:
        if self.client is None:
            try:
                import anthropic
            except ImportError:
                raise Unavailable(INSTALL) from None
            self.client = anthropic.Anthropic()

    def ask(self, text: str) -> str:
        """Send ``text`` and return the model's reply."""
        import anthropic

        self.messages.append({"role": "user", "content": text})
        try:
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=MAX_TOKENS,
                output_config={"effort": "high"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=self.messages,
            ) as stream:
                response = stream.get_final_message()
        except anthropic.AuthenticationError:
            raise Unavailable(
                "The API key was refused. Set ANTHROPIC_API_KEY to a valid key."
            ) from None
        except anthropic.APIConnectionError:
            raise Unavailable(
                "The tool could not reach the API. Check the internet connection."
            ) from None
        except anthropic.APIStatusError as e:
            raise Unavailable(
                f"The API answered with an error ({e.status_code}): {e.message}"
            ) from None
        if response.stop_reason == "refusal":
            raise Unavailable(f"{self.model} declined the task.")
        if response.stop_reason == "max_tokens":
            raise Unavailable(f"{self.model}'s reply was too long and was cut off.")
        # the whole reply goes back, so the next turn continues from it
        self.messages.append({"role": "assistant", "content": response.content})
        return "".join(b.text for b in response.content if b.type == "text")
