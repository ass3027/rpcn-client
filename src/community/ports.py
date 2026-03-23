"""Repository port (interface) for the community board."""

from abc import ABC, abstractmethod


class CommunityRepository(ABC):

    @abstractmethod
    async def init(self) -> None:
        """Initialise the backing store (create tables, pool, etc.)."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources held by the backing store."""

    # -- Posts ---------------------------------------------------------------

    @abstractmethod
    async def list_posts(self, page: int, page_size: int) -> tuple[list[dict], int]:
        """Return (posts, total_count). Each post dict includes a comment_count key."""

    @abstractmethod
    async def get_post(self, post_id: int) -> dict:
        """Return a single post or raise PostNotFoundError."""

    @abstractmethod
    async def get_post_comments(self, post_id: int) -> list[dict]:
        """Return flat list of comments for *post_id*, ordered by created_at ASC."""

    @abstractmethod
    async def create_post(self, author: str, body: str) -> dict:
        """Insert a new post and return it."""

    @abstractmethod
    async def delete_post(self, post_id: int, user: str) -> None:
        """Delete a post owned by *user*, or raise PostNotFoundError / OwnershipError."""

    # -- Comments ------------------------------------------------------------

    @abstractmethod
    async def create_comment(
        self,
        post_id: int,
        author: str,
        body: str,
        parent_id: int | None = None,
    ) -> dict:
        """Add a comment. Raises PostNotFoundError, CommentNotFoundError, NestingDepthError."""

    # -- Thumbs (posts only) -------------------------------------------------

    @abstractmethod
    async def toggle_thumb(self, post_id: int, voter: str, direction: int) -> dict:
        """Toggle a thumb vote on a post. Returns dict with thumbs_up, thumbs_down."""
