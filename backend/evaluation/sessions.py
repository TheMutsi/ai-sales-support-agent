"""Sessions for the evaluation runner: it logs in as a client does, with a session for the case's
customer (or an anonymous one) in a conversation of its own.

Every `open` creates a fresh conversation, so each case and each `--trials` repetition starts
from an empty history; reusing one would feed an earlier run's exchange to the next as context.
Messages before a case's last are stored as that conversation's history; the runner sends the last.

The session is minted with the app's signing key, not through `/api/auth/login`: what's under test
is the agent. Each run leaves small conversation rows until the retention job (not written yet).
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.conversations import create_anonymous, resolve_for_login
from app.auth.scopes import IdentityLevel
from app.auth.session import issue_session_token
from app.core.config import get_settings
from app.db.models import Customer, Message, Tenant
from app.db.seed import DEV_TENANT_API_KEY
from app.db.session import SessionLocal

from .schemas import EvalCase, EvalIdentity

_SESSION_TTL = timedelta(hours=6)  # outlasts a full run of many trials on a slow model


@dataclass(frozen=True)
class CaseSession:
    token: str
    conversation_id: uuid.UUID


class CaseSessions:
    def __init__(self, db: Session, emails: Iterable[str]):
        wanted = {email for email in emails if email}
        tenant = db.execute(
            select(Tenant).where(Tenant.api_key == DEV_TENANT_API_KEY)
        ).scalar_one_or_none()
        self._tenant_id = tenant.id if tenant else None
        self._customers: dict[str, uuid.UUID] = {}
        if tenant is not None:
            rows = db.execute(
                select(Customer.email, Customer.id).where(
                    Customer.email.in_(wanted), Customer.tenant_id == tenant.id
                )
            ).all()
            self._customers = dict(rows)
        missing = sorted(wanted - self._customers.keys())
        if missing:
            raise ValueError(
                f"customers not found in the dev tenant (re-run `python -m app.db.seed`): {missing}"
            )

    def open(self, case: EvalCase) -> CaseSession:
        anonymous = case.identity is EvalIdentity.ANONYMOUS
        customer_id = None if anonymous else self._customers[case.customer_email]
        level = IdentityLevel.ANONYMOUS if anonymous else IdentityLevel.STORE_LOGIN
        now = datetime.now(UTC)
        with SessionLocal() as db:
            if anonymous:
                conversation = create_anonymous(db, tenant_id=self._tenant_id, now=now)
            else:
                conversation = resolve_for_login(
                    db,
                    tenant_id=self._tenant_id,
                    customer_id=customer_id,
                    level=level,
                    conversation_id=None,
                    now=now,
                )
            _store_history(db, conversation, case.messages[:-1], now)
            conversation_id = conversation.id
        token, _ = issue_session_token(
            tenant_id=self._tenant_id,
            conversation_id=conversation_id,
            customer_id=customer_id,
            level=level,
            signing_key=get_settings().session_signing_key,
            ttl=_SESSION_TTL,
        )
        return CaseSession(token=token, conversation_id=conversation_id)


def _store_history(db: Session, conversation, history, now: datetime) -> None:
    """Stores a case's earlier messages as the chat would: numbered, replies linked to their question."""
    last_user_seq = None
    for message in history:
        conversation.last_seq += 1
        is_user = message.role == "user"
        db.add(
            Message(
                conversation_id=conversation.id,
                seq=conversation.last_seq,
                role=message.role,
                content=message.content,
                client_message_id=uuid.uuid4() if is_user else None,
                reply_to_seq=None if is_user else last_user_seq,
                created_at=now,
            )
        )
        last_user_seq = conversation.last_seq if is_user else None
    db.commit()
