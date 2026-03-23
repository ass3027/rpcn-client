"""Pydantic request/response DTOs for the community board."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# --- Requests ---

class SetIdentityRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)


class CreatePostRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=1000)


class CreateCommentRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=1000)
    parent_id: int | None = None


class ThumbRequest(BaseModel):
    direction: int = Field(..., description="1 for thumbs up, -1 for thumbs down")

    @field_validator("direction")
    @classmethod
    def must_be_plus_or_minus_one(cls, v: int) -> int:
        if v not in (1, -1):
            raise ValueError("direction must be 1 or -1")
        return v


# --- Responses ---

class PostSummary(BaseModel):
    id: int
    author: str
    body: str
    thumbs_up: int
    thumbs_down: int
    created_at: datetime
    comment_count: int = 0


class CommentOut(BaseModel):
    id: int
    post_id: int
    parent_id: int | None
    author: str
    body: str
    created_at: datetime
    replies: list["CommentOut"] = []


class PostDetail(BaseModel):
    id: int
    author: str
    body: str
    thumbs_up: int
    thumbs_down: int
    created_at: datetime
    comments: list[CommentOut] = []


class PostListResponse(BaseModel):
    posts: list[PostSummary]
    total: int
    page: int
    page_size: int
