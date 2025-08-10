import re


def sanitize_prompt(prompt: str) -> str:
    """Trim leading/trailing spaces and collapse multiple internal whitespace.

    Args:
        prompt: Raw prompt string.

    Returns:
        Sanitized prompt with single spaces separating words.
    """
    # Strip leading/trailing whitespace
    trimmed = prompt.strip()
    # Collapse all sequences of whitespace into a single space
    return re.sub(r"\s+", " ", trimmed)


def respond(prompt: str) -> str:
    """Simple responder that acknowledges the prompt.

    Args:
        prompt: Already sanitized prompt.

    Returns:
        "Empty prompt." if the sanitized prompt is empty,
        otherwise an acknowledgement string.
    """
    if not prompt:
        return "Empty prompt."
    return f"ACK:{prompt}"


def process_pipeline(raw: str) -> dict:
    """Process the full logic pipeline.

    Args:
        raw: Raw user input.

    Returns:
        dict: mapping of original input, sanitized version and response.
    """
    clean = sanitize_prompt(raw)
    output = respond(clean)
    return {"input": raw, "clean": clean, "output": output}
