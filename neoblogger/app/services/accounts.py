"""Member account workflows (spec §4, tech-req §8).

Passwords and security answers are Argon2id-hashed; answers are stored
normalized (trimmed, lowercased) and never displayed back. The first
member becomes administrator and publisher (spec §2); display names are
immutable (Appendix B D1).
"""

import asyncio

from ..repositories.comments import CommentRepository
from ..repositories.documents import MemberDocument
from ..repositories.members import MemberAlreadyExistsError, MemberRepository
from ..security.hashing import (
    async_hash_secret,
    async_verify_secret,
    normalize_answer,
)
from .visibility import ArticleVisibility

__all__ = [
    "SECURITY_QUESTIONS",
    "SECURITY_QUESTION_LABELS",
    "AccountDisabledError",
    "AccountService",
]

SECURITY_QUESTION_LABELS: dict[str, str] = {
    "first-pet": "What was your first pet's name?",
    "elementary-school": "Which elementary school did you attend?",
    "birth-city": "In which city were you born?",
    "mothers-maiden-name": "What is your mother's maiden name?",
    "favorite-book": "Which book is your favorite?",
    "favorite-food": "Which food is your favorite?",
    "first-car": "What was your first car?",
}

SECURITY_QUESTIONS: tuple[str, ...] = tuple(SECURITY_QUESTION_LABELS)


class AccountDisabledError(Exception):
    """Raised when a disabled account attempts authentication or recovery."""


class AccountService:
    """Registration, authentication, recovery, and credential rotation."""

    def __init__(
        self,
        members: MemberRepository,
        comments: CommentRepository,
        articles_visibility: ArticleVisibility,
    ) -> None:
        self._members = members
        self._comments = comments
        self._visibility = articles_visibility

    async def register(
        self,
        display_name: str,
        email: str,
        password: str,
        question_code: str,
        answer: str,
    ) -> tuple[str, bool]:
        """Create a member; returns (hex id, promoted-to-administrator).

        The first registered member becomes administrator and publisher
        with a congratulatory notice (spec §2, §4.1). The first-member
        check runs inside the single insert work unit, so concurrent
        registrations cannot both win.
        """
        display_name = display_name.strip()
        email = email.strip().lower()
        if not display_name:
            raise ValueError("a display name is required")
        if not email:
            raise ValueError("an email address is required")
        if not password:
            raise ValueError("a password is required")
        if not answer.strip():
            raise ValueError("a security answer is required")
        if question_code not in SECURITY_QUESTIONS:
            raise ValueError("choose a security question from the list")
        # Fast pre-checks before the costly Argon2 hashes; the insert work
        # unit re-checks authoritatively against concurrent registrations.
        if await self._members.by_email(email) is not None:
            raise MemberAlreadyExistsError("email already registered")
        if await self._members.by_display_name(display_name) is not None:
            raise MemberAlreadyExistsError("display name already registered")
        password_hash = ""
        answer_hash = ""
        async with asyncio.TaskGroup() as group:

            async def _hash_password() -> None:
                nonlocal password_hash
                password_hash = await async_hash_secret(password)

            async def _hash_answer() -> None:
                nonlocal answer_hash
                answer_hash = await async_hash_secret(normalize_answer(answer))

            group.create_task(_hash_password())
            group.create_task(_hash_answer())
        return await self._members.create_first_or_member(
            display_name,
            email,
            password_hash,
            question_code,
            answer_hash,
        )

    async def authenticate(self, email: str, password: str) -> MemberDocument | None:
        """Verify credentials; ``None`` when they do not match (§4.2).

        A disabled account raises :class:`AccountDisabledError` so callers
        show the distinct "contact an administrator" notice.
        """
        member = await self._members.by_email(email.strip().lower())
        if member is None:
            return None
        if not await async_verify_secret(member["password_hash"], password):
            return None
        if not member["active"]:
            raise AccountDisabledError("account is disabled")
        return member

    async def recover(self, email: str, answer: str, new_password: str) -> bool:
        """Reset a password after a matching security answer (§4.4)."""
        member = await self._members.by_email(email.strip().lower())
        if member is None:
            return False
        if not member["active"]:
            raise AccountDisabledError("account is disabled")
        if not new_password:
            return False
        normalized = normalize_answer(answer)
        if not await async_verify_secret(member["security_answer_hash"], normalized):
            return False
        password_hash = await async_hash_secret(new_password)
        await self._members.update_credentials(
            member["_id"],
            email=member["email"],
            password_hash=password_hash,
            security_question_code=member["security_question_code"],
            security_answer_hash=member["security_answer_hash"],
        )
        return True

    async def update_credentials(
        self,
        member: MemberDocument,
        *,
        new_email: str,
        new_password: str | None,
        question_code: str,
        answer: str,
    ) -> int:
        """Rotate credentials; the question/answer is mandatory (§4.6)."""
        new_email = new_email.strip().lower()
        if not new_email:
            raise ValueError("an email address is required")
        if not answer.strip():
            raise ValueError("a security answer is required")
        if question_code not in SECURITY_QUESTIONS:
            raise ValueError("choose a security question from the list")
        existing = await self._members.by_email(new_email)
        if existing is not None and existing["_id"] != member["_id"]:
            raise MemberAlreadyExistsError("email already registered")
        password_hash = member["password_hash"]
        answer_hash = ""
        async with asyncio.TaskGroup() as group:

            async def _hash_new_password() -> None:
                nonlocal password_hash
                if new_password:
                    password_hash = await async_hash_secret(new_password)

            async def _hash_new_answer() -> None:
                nonlocal answer_hash
                answer_hash = await async_hash_secret(normalize_answer(answer))

            group.create_task(_hash_new_password())
            group.create_task(_hash_new_answer())
        return await self._members.update_credentials(
            member["_id"],
            email=new_email,
            password_hash=password_hash,
            security_question_code=question_code,
            security_answer_hash=answer_hash,
        )

    async def profile_statistics(self, member: MemberDocument) -> dict[str, int]:
        """Statistics cards for the profile page (spec §4.5).

        Counts run in the engine; article bodies are never loaded (§14).
        """
        counts = await self._visibility.count_by_author(member["display_name"])
        comments_written = await self._comments.count_by_author(member["display_name"])
        published = counts["published"]
        drafts = counts["draft"]
        return {
            "published": published,
            "drafts": drafts,
            "comments_written": comments_written,
            "contributions": published + drafts + comments_written,
        }
