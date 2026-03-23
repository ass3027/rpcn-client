"""FastAPI router for the community board."""

from fastapi import APIRouter, Depends, Query, Response

from community import models, service
from community.identity import get_user
from shared.cache import cache_get, cache_set, cache_delete_pattern
from shared.settings import get_settings

router = APIRouter()


def _ttl() -> int:
    return get_settings().cache_ttl_community


def _invalidate_posts():
    cache_delete_pattern("community:posts:*")


def _invalidate_post(post_id: int):
    cache_delete_pattern(f"community:post:{post_id}")


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

@router.post("/identity")
def set_identity(req: models.SetIdentityRequest, response: Response):
    response.set_cookie("community_user", req.name.strip()[:50], httponly=True, samesite="lax")
    return {"user": req.name.strip()[:50]}


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------

@router.get("/posts", response_model=models.PostListResponse)
async def list_posts(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    cache_key = f"community:posts:p{page}:s{page_size}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    posts, total = await service.list_posts(page, page_size)
    result = {"posts": posts, "total": total, "page": page, "page_size": page_size}
    cache_set(cache_key, result, _ttl())
    return result


@router.post("/posts", status_code=201)
async def create_post(req: models.CreatePostRequest, user: str = Depends(get_user)):
    post = await service.create_post(user, req.body)
    _invalidate_posts()
    return post


@router.get("/posts/{post_id}", response_model=models.PostDetail)
async def get_post(post_id: int):
    cache_key = f"community:post:{post_id}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    post = await service.get_post(post_id)
    comments = await service.get_post_comments(post_id)

    # nest replies under their parent
    top_level: list[dict] = []
    by_id: dict[int, dict] = {}
    for c in comments:
        c["replies"] = []
        by_id[c["id"]] = c
    for c in comments:
        if c["parent_id"] and c["parent_id"] in by_id:
            by_id[c["parent_id"]]["replies"].append(c)
        else:
            top_level.append(c)

    post["comments"] = top_level
    cache_set(cache_key, post, _ttl())
    return post


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(post_id: int, user: str = Depends(get_user)):
    await service.delete_post(post_id, user)
    _invalidate_posts()
    _invalidate_post(post_id)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

@router.post("/posts/{post_id}/comments", status_code=201)
async def create_comment(
    post_id: int,
    req: models.CreateCommentRequest,
    user: str = Depends(get_user),
):
    comment = await service.create_comment(post_id, user, req.body, req.parent_id)
    _invalidate_post(post_id)
    return comment


# ---------------------------------------------------------------------------
# Thumbs (posts only)
# ---------------------------------------------------------------------------

@router.post("/posts/{post_id}/thumb")
async def thumb_post(post_id: int, req: models.ThumbRequest, user: str = Depends(get_user)):
    result = await service.toggle_thumb(post_id, user, req.direction)
    _invalidate_posts()
    _invalidate_post(post_id)
    return result
