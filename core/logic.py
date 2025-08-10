from __future__ import annotations

"""Core logic functions for the CodexGPT application.

This module exposes small utility functions that can be reused without
triggering side effects on import. All functions provide type hints and
perform basic type validation. The module targets Python 3.10 or newer.
"""

from typing import Dict

__all__ = ["sanitize_prompt", "respond", "process_pipeline"]


def sanitize_prompt(s: str) -> str:
    """Trim *s* and collapse multiple whitespace characters into one space.

    Parameters
    ----------
    s:
        The input string to sanitize.

    Returns
    -------
    str
        A cleaned version of *s* with normalized whitespace.

    Raises
    ------
    TypeError
        If *s* is not an instance of :class:`str`.
    """

    if not isinstance(s, str):
        raise TypeError("s must be a string")

    return " ".join(s.strip().split())


def respond(prompt: str) -> str:
    """Generate a response string for *prompt*.

    The prompt is first sanitized using :func:`sanitize_prompt`.
    If the sanitized prompt is empty, ``"Empty prompt."`` is returned.
    Otherwise, an acknowledgement string prefixed with ``"ACK:"`` is
    returned.

    Parameters
    ----------
    prompt:
        The user input to handle.

    Returns
    -------
    str
        The generated response.

    Raises
    ------
    TypeError
        If *prompt* is not an instance of :class:`str`.
    """

    clean = sanitize_prompt(prompt)
    if not clean:
        return "Empty prompt."
    return f"ACK:{clean}"


def process_pipeline(prompt: str) -> Dict[str, str]:
    """Process *prompt* through the application pipeline.

    Parameters
    ----------
    prompt:
        The original user input.

    Returns
    -------
    dict
        A dictionary with the original input, the sanitized prompt, and the
        generated output.

    Raises
    ------
    TypeError
        If *prompt* is not an instance of :class:`str`.
    """

    clean = sanitize_prompt(prompt)
    output = respond(prompt)
    return {"input": prompt, "clean": clean, "output": output}
