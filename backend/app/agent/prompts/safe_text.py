import re

_WHITESPACE_RUN = re.compile(r"\s+")
_NEUTRALISED = str.maketrans({"<": "‹", ">": "›", "|": "¦"})


def prompt_safe(text: str, max_length: int) -> str:
    collapsed = _WHITESPACE_RUN.sub(" ", text).strip().translate(_NEUTRALISED)
    if len(collapsed) <= max_length:
        return collapsed
    return collapsed[: max_length - 1].rstrip() + "…"
