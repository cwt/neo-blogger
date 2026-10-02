"""Member account workflows (spec §4, tech-req §8).

Passwords and security answers are Argon2id-hashed; answers are stored
normalized (trimmed, lowercased) and never displayed back. The first
member becomes administrator and publisher (spec §2); display names are
immutable (Appendix B D1).
"""

from ..repositories.comments import CommentRepository
from ..repositories.documents import MemberDocument
from ..repositories.members import MemberAlreadyExistsError, MemberRepository
from ..security.hashing import hash_secret, verify_secret
from .visibility import ArticleVisibility

__all__ = ["SECURITY_QUESTIONS", "AccountDisabledError", "AccountService"]

SECURITY_QUESTIONS: tuple[str, ...] = (
    "first-pet",
    "elementary-school",
    "birth-city",
    "mothers-maiden-name",
    "favorite-book",
    "favorite-food",
    "first-car",
)


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
        password_hash = hash_secret(password)
        answer_hash = hash_secret(answer.strip().lower())
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
        member = await self._members.by_email(email)
        if member is None:
            return None
        if not verify_secret(member["password_hash"], password):
            return None
        if not member["active"]:
            raise AccountDisabledError("account is disabled")
        return member

    async def recover(self, email: str, answer: str, new_password: str) -> bool:
        """Reset a password after a matching security answer (§4.4)."""
        member = await self._members.by_email(email)
        if member is None:
            return False
        if not member["active"]:
            raise AccountDisabledError("account is disabled")
        normalized = answer.strip().lower()
        if not verify_secret(member["security_answer_hash"], normalized):
            return False
        password_hash = hash_secret(new_password)
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
    ) -> None:
        """Rotate credentials; the question/answer is mandatory (§4.6)."""
        existing = await self._members.by_email(new_email)
        if existing is not None and existing["_id"] != member["_id"]:
            raise MemberAlreadyExistsError("email already registered")
        password_hash = (
            hash_secret(new_password) if new_password else member["password_hash"]
        )
        answer_hash = hash_secret(answer.strip().lower())
        await self._members.update_credentials(
            member["_id"],
            email=new_email,
            password_hash=password_hash,
            security_question_code=question_code,
            security_answer_hash=answer_hash,
        )

    async def profile_statistics(self, member: MemberDocument) -> dict[str, int]:
        """Statistics cards for the profile page (spec §4.5)."""
        published = 0
        drafts = 0
        for article in await self._visibility.articles_by_author(
            member["display_name"]
        ):
            if article["status"] == "published":
                published += 1
            else:
                drafts += 1
        comments_written = await self._comments.count_by_author(member["display_name"])
        return {
            "published": published,
            "drafts": drafts,
            "comments_written": comments_written,
            "contributions": published + drafts + comments_written,
        }
