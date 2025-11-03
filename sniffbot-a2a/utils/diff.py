# utils/diff.py
import difflib
import logging
from typing import List

logger = logging.getLogger(__name__)


def create_diff(original: str, fixed: str) -> str:
    """
    Generate a unified diff between original and fixed code.
    Used in:
      - A2AMessage parts (text)
      - Artifact(name="diff")

    A2A Compliance:
      - Returns plain text string
      - Safe with empty/malformed input
      - No external dependencies beyond stdlib
      - Never raises

    Args:
        original (str): Original code
        fixed (str): Corrected code

    Returns:
        str: Unified diff in ```diff\n...\n``` format
    """
    # Normalize inputs
    original = original or ""
    fixed = fixed or ""

    # Split into lines and add trailing newline for diff consistency
    original_lines = original.splitlines(keepends=True)
    fixed_lines = fixed.splitlines(keepends=True)

    # Ensure both end with newline (diff standard)
    if original_lines and not original_lines[-1].endswith('\n'):
        original_lines[-1] += '\n'
    if fixed_lines and not fixed_lines[-1].endswith('\n'):
        fixed_lines[-1] += '\n'

    # Generate unified diff
    try:
        diff = difflib.unified_diff(
            original_lines,
            fixed_lines,
            fromfile="original",
            tofile="fixed",
            lineterm="",  # We manage newlines manually
            n=3  # Context lines
        )
        diff_lines = list(diff)

        # If no changes, return empty diff block
        if not diff_lines:
            return "```diff\n# No changes detected\n```"

        # Join and wrap in code block
        diff_text = "".join(diff_lines).rstrip() + "\n"
        return f"```diff\n{diff_text}```"

    except Exception as e:
        logger.error(f"Diff generation failed: {e}")
        return "```diff\n# Error generating diff\n```"