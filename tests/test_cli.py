import subprocess
import sys


def run_cli(*args):
    """Helper to execute the CLI module with given arguments."""
    return subprocess.run(
        [sys.executable, "-m", "cli", *args],
        capture_output=True,
        text=True,
    )


def test_ping_command_returns_ack():
    """`python -m cli ping` should return exit code 0 and ACK the argument."""
    result = run_cli("ping")
    assert result.returncode == 0
    assert "ACK:ping" in result.stdout


def test_missing_argument_shows_usage():
    """Running `python -m cli` without arguments should error with usage info."""
    result = run_cli()
    assert result.returncode == 2
    assert "usage" in result.stderr.lower()
