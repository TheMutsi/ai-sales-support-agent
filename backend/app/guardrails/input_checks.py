"""Signal-tagging for the incoming message.

`flag_prompt_injection_signals` itself only tags known attack shapes — it
never blocks or rewrites anything. What a caller does with those tags is its
own call: `app/agent/nodes/input_guardrail.py` uses them to short-circuit the
graph outright (the production-grade behavior CLAUDE.md's guardrails section
asks for), while Stage 9's evaluation suite can use the same tags just to
measure how often each attack shape shows up, without needing a second
implementation of the pattern matching.

Detection stays intentionally narrow — the curated shapes below, not generic
suspicious wording — because a regex match is weaker evidence than a tool
result. The Stage 6 adversarial testing already showed the base model
refusing these attempts on its own; this module exists to make that refusal
unconditional instead of trusting the model to keep doing it.
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
