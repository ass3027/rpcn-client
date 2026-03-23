"""PostgreSQL adapter for the community repository."""

import logging

import asyncpg

from community.exceptions import (
    PostNotFoundError,
    CommentNotFoundError,
    OwnershipError,
    NestingDepthError,
)
from community.ports import CommunityRepository

logger = logging.getLogger(__name__)

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS posts (
        id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        author      TEXT    NOT NULL,
        body        TEXT    NOT NULL CHECK(length(body) <= 1000),
        thumbs_up   INTEGER NOT NULL DEFAULT 0,
        thumbs_down INTEGER NOT NULL DEFAULT 0,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comments (
        id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
        parent_id   INTEGER REFERENCES comments(id) ON DELETE CASCADE,
        author      TEXT    NOT NULL,
        body        TEXT    NOT NULL CHECK(length(body) <= 1000),
        created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id)",
    "CREATE INDEX IF NOT EXISTS idx_comments_parent ON comments(parent_id)",
    """
    CREATE TABLE IF NOT EXISTS thumbs (
        id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
        voter       TEXT    NOT NULL,
        direction   INTEGER NOT NULL CHECK(direction IN (1,-1)),
        created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(post_id, voter)
    )
    """,
]


class PostgresCommunityRepository(CommunityRepository):

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def init(self) -> None:
        logger.info(
            "Connecting to community DB at %s",
            self._dsn.split("@")[-1] if "@" in self._dsn else self._dsn,
        )
        self._pool = await asyncpg.create_pool(dsn=self._dsn, min_size=2, max_size=10)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for stmt in _SCHEMA_STATEMENTS:
                    await conn.execute(stmt)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Community DB pool closed")

    @property
    def _db(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Community DB not initialized — call init() first")
        return self._pool

    # -- Posts ---------------------------------------------------------------

    async def list_posts(self, page: int, page_size: int) -> tuple[list[dict], int]:
        offset = (page - 1) * page_size
        rows = await self._db.fetch(
            """
            SELECT p.*, COALESCE(c.cnt, 0) AS comment_count,
                   COUNT(*) OVER() AS total
            FROM posts p
            LEFT JOIN (SELECT post_id, COUNT(*) AS cnt FROM comments GROUP BY post_id) c
                ON c.post_id = p.id
            ORDER BY p.created_at DESC
            LIMIT $1 OFFSET $2
            """,
            page_size, offset,
        )
        total = rows[0]["total"] if rows else 0
        return [dict(r) for r in rows], total

    async def get_post(self, post_id: int) -> dict:
        row = await self._db.fetchrow("SELECT * FROM posts WHERE id = $1", post_id)
        if row is None:
            raise PostNotFoundError("Post not found")
        return dict(row)

    async def get_post_comments(self, post_id: int) -> list[dict]:
        rows = await self._db.fetch(
            "SELECT * FROM comments WHERE post_id = $1 ORDER BY created_at ASC",
            post_id,
        )
        return [dict(r) for r in rows]

    async def create_post(self, author: str, body: str) -> dict:
        row = await self._db.fetchrow(
            "INSERT INTO posts (author, body) VALUES ($1, $2) RETURNING *",
            author, body,
        )
        return dict(row)

    async def delete_post(self, post_id: int, user: str) -> None:
        row = await self._db.fetchrow("SELECT author FROM posts WHERE id = $1", post_id)
        if row is None:
            raise PostNotFoundError("Post not found")
        if row["author"] != user:
            raise OwnershipError("Not your post")
        await self._db.execute("DELETE FROM posts WHERE id = $1", post_id)

    # -- Comments ------------------------------------------------------------

    async def create_comment(
        self, post_id: int, author: str, body: str, parent_id: int | None = None
    ) -> dict:
        row = await self._db.fetchrow("SELECT id FROM posts WHERE id = $1", post_id)
        if row is None:
            raise PostNotFoundError("Post not found")

        if parent_id is not None:
            row = await self._db.fetchrow(
                "SELECT parent_id FROM comments WHERE id = $1 AND post_id = $2",
                parent_id, post_id,
            )
            if row is None:
                raise CommentNotFoundError("Parent comment not found")
            if row["parent_id"] is not None:
                raise NestingDepthError("Cannot reply to a reply (max 1-depth nesting)")

        row = await self._db.fetchrow(
            "INSERT INTO comments (post_id, parent_id, author, body) VALUES ($1, $2, $3, $4) RETURNING *",
            post_id, parent_id, author, body,
        )
        return dict(row)

    # -- Thumbs (posts only) -------------------------------------------------

    async def toggle_thumb(self, post_id: int, voter: str, direction: int) -> dict:
        async with self._db.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT id FROM posts WHERE id = $1", post_id
                )
                if row is None:
                    raise PostNotFoundError("Post not found")

                existing = await conn.fetchrow(
                    "SELECT direction FROM thumbs WHERE post_id = $1 AND voter = $2",
                    post_id, voter,
                )

                if existing and existing["direction"] == direction:
                    await conn.execute(
                        "DELETE FROM thumbs WHERE post_id = $1 AND voter = $2",
                        post_id, voter,
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO thumbs (post_id, voter, direction)
                        VALUES ($1, $2, $3)
                        ON CONFLICT(post_id, voter)
                        DO UPDATE SET direction = excluded.direction
                        """,
                        post_id, voter, direction,
                    )

                counts = await conn.fetchrow(
                    """
                    SELECT
                        COALESCE(SUM(CASE WHEN direction = 1 THEN 1 ELSE 0 END), 0) AS up,
                        COALESCE(SUM(CASE WHEN direction = -1 THEN 1 ELSE 0 END), 0) AS down
                    FROM thumbs
                    WHERE post_id = $1
                    """,
                    post_id,
                )
                up, down = counts["up"], counts["down"]
                await conn.execute(
                    "UPDATE posts SET thumbs_up = $1, thumbs_down = $2 WHERE id = $3",
                    up, down, post_id,
                )

        return {"thumbs_up": up, "thumbs_down": down}
