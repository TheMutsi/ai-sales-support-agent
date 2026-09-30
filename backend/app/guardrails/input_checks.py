"""Lightweight signal-tagging for the incoming message — not a blocking filter.

CLAUDE.md is explicit: a prompt-injection attempt should be refused and the
agent should continue normally, without special-casing detection in a way
that itself leaks the system prompt. So this never blocks or rewrites a
message — it only tags known attack shapes for observability (LangSmith trace
metadata, logs). That's useful because the Stage 6 adversarial testing showed
the base model refusing these attempts on its own; tagging lets Stage 9's
evaluation suite actually measure how often that holds, instead of assuming it.
"""

import re

_INJECTION_SIGNAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "instruction_override": re.compile(
        r"(ignore|disregard|forget|olvida|ignora) (all |your |previous |the |todas? (las )?|tus )*"
        r"(instructions|rules|prompt|instrucciones|reglas)",
        re.IGNORECASE,
    ),
    "system_prompt_extraction": re.compile(
        r"(system prompt|your instructions|repeat (your|the) prompt|reveal .*(prompt|instructions)|"
        r"prompt del sistema|tus instrucciones)",
        re.IGNORECASE,
    ),
    "code_execution_attempt": re.compile(
        r"(run|execute|eval|ejecuta|corre) (this|the following|este|el siguiente)?\s*"
        r"(python|code|script|command|c[oó]digo|comando)",
        re.IGNORECASE,
    ),
    "db_manipulation_attempt": re.compile(
        r"\b(drop table|delete from|update .* set|insert into|;\s*--)\b",
        re.IGNORECASE,
    ),
    "roleplay_jailbreak": re.compile(
        r"(pretend|act as|roleplay as|actua como|finge ser) (you('re| are))? ?(a|an|un|una)? ?"
        r".*(no rules|without restrictions|sin reglas|sin restricciones|dan|developer mode)",
        re.IGNORECASE,
    ),
}


def flag_prompt_injection_signals(message_text: str) -> list[str]:
    return [
        tag for tag, pattern in _INJECTION_SIGNAL_PATTERNS.items() if pattern.search(message_text)
    ]
