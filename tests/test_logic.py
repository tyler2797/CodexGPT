import sys
from pathlib import Path

import pytest

# Ensure the parent directory (project root) is on sys.path for imports
sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.logic import sanitize_prompt, respond, process_pipeline


def test_sanitize_prompt_basic() -> None:
    assert sanitize_prompt("  hello   world \n\t") == "hello world"


def test_sanitize_prompt_type_error() -> None:
    with pytest.raises(TypeError):
        sanitize_prompt(123)  # type: ignore[arg-type]


def test_respond_empty() -> None:
    assert respond(" \n\t ") == "Empty prompt."


def test_respond_ack() -> None:
    assert respond(" foo   bar ") == "ACK:foo bar"


def test_process_pipeline() -> None:
    prompt = "  foo \t bar   "
    result = process_pipeline(prompt)
    assert result == {
        "input": prompt,
        "clean": "foo bar",
        "output": "ACK:foo bar",
    }


def test_process_pipeline_empty() -> None:
    result = process_pipeline("   ")
    assert result == {
        "input": "   ",
        "clean": "",
        "output": "Empty prompt.",
    }
