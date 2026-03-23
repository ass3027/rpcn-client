"""Business logic for the community board — delegates to the repository port."""

from community.db import get_repo


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------

async def list_posts(page: int, page_size: int) -> tuple[list[dict], int]:
    return await get_repo().list_posts(page, page_size)


async def get_post(post_id: int) -> dict:
    return await get_repo().get_post(post_id)


async def get_post_comments(post_id: int) -> list[dict]:
    return await get_repo().get_post_comments(post_id)


async def create_post(author: str, body: str) -> dict:
    return await get_repo().create_post(author, body)


async def delete_post(post_id: int, user: str):
    await get_repo().delete_post(post_id, user)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

async def create_comment(post_id: int, author: str, body: str, parent_id: int | None = None) -> dict:
    return await get_repo().create_comment(post_id, author, body, parent_id)


# ---------------------------------------------------------------------------
# Thumbs (posts only)
# ---------------------------------------------------------------------------

async def toggle_thumb(post_id: int, voter: str, direction: int):
    return await get_repo().toggle_thumb(post_id, voter, direction)
