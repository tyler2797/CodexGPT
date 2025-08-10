import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from core.logic import sanitize_prompt, respond, process_pipeline


def test_sanitize_prompt_collapses_spaces_and_trims():
    raw = "  hello   world "
    assert sanitize_prompt(raw) == "hello world"


def test_respond_empty_prompt_returns_message():
    assert respond("") == "Empty prompt."


def test_respond_ping_returns_ack():
    assert respond("ping") == "ACK:ping"


def test_process_pipeline_returns_coherent_dict():
    data = process_pipeline("  hi  ")
    assert data == {"input": "  hi  ", "clean": "hi", "output": "ACK:hi"}
