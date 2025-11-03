# utils/code_extractor.py
import re
from typing import Tuple, List, Dict, Any
import logging

# Configure logger (same as main.py)
logger = logging.getLogger(__name__)


def extract_code(text: str) -> Tuple[str, str]:
    """
    Extract the most likely code snippet from a user message.
    Supports:
      • Fenced code blocks: ```python\n...\n```
      • Inline code: `x = 1`
      • Indented blocks (4+ spaces or tabs)
      • Heuristic raw code lines (def, function, const, etc.)

    Returns:
        (code: str, language_hint: str)

    A2A Compliance:
        • Only processes `MessagePart(kind="text")`
        • No external I/O
        • Never raises exceptions
        • Always returns valid strings
    """
    if not text or not isinstance(text, str):
        logger.debug("extract_code: input is empty or not string")
        return "", ""

    text = text.strip()
    if not text:
        return "", ""

    # ------------------------------------------------------------------
    # 1. Fenced code block (highest priority)
    # ------------------------------------------------------------------
    logger.debug(f"Input text: '{text}'")
    fenced_match = re.search(r"```(\w+)?\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        lang = (fenced_match.group(1) or "").lower()
        code = fenced_match.group(2).rstrip()
        if code:
            logger.debug(f"extract_code: found fenced block, lang='{lang}'")
            return code, lang or "unknown"

    # ------------------------------------------------------------------
    # 2. Inline code (single or triple backticks)
    # ------------------------------------------------------------------
    inline_match = re.search(r"`{1,3}(?!`)(.*?)(?<!`)`{1,3}", text)
    if inline_match:
        code = inline_match.group(1).strip()
        if code:
            logger.debug("extract_code: found inline code")
            return code, "unknown"

    # ------------------------------------------------------------------
    # 3. Indented code block (4+ spaces or tab at start of line)
    # ------------------------------------------------------------------
    indented_lines = []
    for line in text.splitlines():
        if re.match(r"^ {4,}|\t", line):
            indented_lines.append(line)

    if indented_lines:
        # Dedent
        code = "\n".join(
            re.sub(r"^ {4,}|\t", "", line, count=1) for line in indented_lines
        ).strip()
        if code:
            lang = _detect_language(code)
            logger.debug(f"extract_code: found indented block, lang='{lang}'")
            return code, lang

    # ------------------------------------------------------------------
    # 4. Heuristic: lines with strong code indicators
    # ------------------------------------------------------------------
    code_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _is_likely_code_line(stripped):
            code_lines.append(line)

    if code_lines:
        code = "\n".join(code_lines).strip()
        lang = _detect_language(code)
        logger.debug(f"extract_code: heuristic match, lang='{lang}'")
        return code, lang

    # ------------------------------------------------------------------
    # 5. No code found
    # ------------------------------------------------------------------
    logger.debug("extract_code: no code detected")
    return "", ""


def _is_likely_code_line(line: str) -> bool:
    """Return True if line looks like code (not prose)"""
    line_lower = line.lower()
    code_keywords = [
        "def ", "function ", "const ", "let ", "var ", "class ", "import ", "from ",
        "async ", "await ", "return ", "if ", "for ", "while ", "select ", "insert ",
        "=>", "->", "{", "}", "(", ")", "[", "]", "=", "==", "+=", ":", ";", "#"
    ]
    return any(kw in line_lower for kw in code_keywords)


def _detect_language(code: str) -> str:
    """Simple, fast language detection based on keywords"""
    if not code:
        return "unknown"

    code_lower = code.lower()

    # Python
    if any(kw in code_lower for kw in ["def ", "print(", "import ", "from ", "self."]):
        return "python"

    # JavaScript / TypeScript
    if any(kw in code_lower for kw in ["function ", "const ", "let ", "var ", "=>", "console.log"]):
        return "javascript"

    # Go
    if any(kw in code_lower for kw in ["func ", "package ", "import ", "type ", "struct "]):
        return "go"

    # SQL
    if any(kw in code_lower for kw in ["select ", "from ", "where ", "insert into", "update ", "delete "]):
        return "sql"

    # Java / C#
    if any(kw in code_lower for kw in ["public class", "void ", "new ", "return "]) and "{" in code:
        return "java"

    # Shell
    if any(kw in code_lower for kw in ["echo ", "$", "export ", "sudo "]) and not "```" in code:
        return "bash"

    return "unknown"