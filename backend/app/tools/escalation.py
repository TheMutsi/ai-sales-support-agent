"""Opening an escalation: the follow-up number the customer is given.

There is no ticket row. The number is kept on the conversation (see `app.chat.turns.finish_turn`),
and what happened is the conversation itself, so no one has to write a summary that could drift
from it.
"""

import secrets

# No 0/O or 1/I/L: the customer may have to read it out or type it.
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_LENGTH = 8


def new_reference() -> str:
    """`MF-7K3Q9X2A`: 31^8 possibilities, so a collision is not a case to plan for (the column is
    unique anyway, and a collision would fail the save, not hand out someone else's number)."""
    return "MF-" + "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
