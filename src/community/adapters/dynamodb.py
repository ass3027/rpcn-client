"""DynamoDB adapter for the community repository."""

import logging
from datetime import datetime, timezone
from decimal import Decimal

import aioboto3
from botocore.exceptions import ClientError

from community.exceptions import (
    PostNotFoundError,
    CommentNotFoundError,
    OwnershipError,
    NestingDepthError,
)
from community.ports import CommunityRepository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COUNTER_KEY = {"PK": "COUNTER", "SK": "COUNTER"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decimal_to_int(d: Decimal | int) -> int:
    return int(d)


def _item_to_post(item: dict) -> dict:
    return {
        "id": _decimal_to_int(item["id"]),
        "author": item["author"],
        "body": item["body"],
        "thumbs_up": _decimal_to_int(item.get("thumbs_up", 0)),
        "thumbs_down": _decimal_to_int(item.get("thumbs_down", 0)),
        "created_at": item["created_at"],
        "comment_count": _decimal_to_int(item.get("comment_count", 0)),
    }


def _item_to_comment(item: dict) -> dict:
    return {
        "id": _decimal_to_int(item["id"]),
        "post_id": _decimal_to_int(item["post_id"]),
        "parent_id": _decimal_to_int(item["parent_id"]) if item.get("parent_id") else None,
        "author": item["author"],
        "body": item["body"],
        "created_at": item["created_at"],
    }


async def _next_id(table) -> int:
    """Atomically increment and return the next integer id."""
    resp = await table.update_item(
        Key=_COUNTER_KEY,
        UpdateExpression="SET current_id = if_not_exists(current_id, :zero) + :inc",
        ExpressionAttributeValues={":zero": 0, ":inc": 1},
        ReturnValues="UPDATED_NEW",
    )
    return int(resp["Attributes"]["current_id"])


# ---------------------------------------------------------------------------
# Table definitions
# ---------------------------------------------------------------------------

_TABLE_SCHEMA = {
    "KeySchema": [
        {"AttributeName": "PK", "KeyType": "HASH"},
        {"AttributeName": "SK", "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "PK", "AttributeType": "S"},
        {"AttributeName": "SK", "AttributeType": "S"},
        {"AttributeName": "GSI1PK", "AttributeType": "S"},
        {"AttributeName": "GSI1SK", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "GSI1",
            "KeySchema": [
                {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
    ],
    "BillingMode": "PAY_PER_REQUEST",
}


class DynamoCommunityRepository(CommunityRepository):
    """Single-table DynamoDB adapter.

    Key layout
    ----------
    Posts:    PK=POST#{id}                   SK=META           GSI1PK=POSTS  GSI1SK={created_at}
    Comments: PK=POST#{post_id}             SK=COMMENT#{id}
    Thumbs:  PK=THUMB#POST#{post_id}        SK=VOTER#{voter}
    Counter: PK=COUNTER                     SK=COUNTER
    """

    def __init__(self, region: str, table_name: str, endpoint_url: str | None = None):
        self._region = region
        self._table_name = table_name
        self._endpoint_url = endpoint_url
        self._session: aioboto3.Session | None = None
        self._resource_ctx = None
        self._resource = None
        self._table = None

    async def init(self) -> None:
        self._session = aioboto3.Session()
        kwargs = {"region_name": self._region}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        self._resource_ctx = self._session.resource("dynamodb", **kwargs)
        self._resource = await self._resource_ctx.__aenter__()

        try:
            self._table = await self._resource.Table(self._table_name)
            await self._table.load()
            logger.info("DynamoDB table '%s' already exists", self._table_name)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.info("Creating DynamoDB table '%s'", self._table_name)
                self._table = await self._resource.create_table(
                    TableName=self._table_name, **_TABLE_SCHEMA
                )
                await self._table.wait_until_exists()
                logger.info("DynamoDB table '%s' created", self._table_name)
            else:
                raise

    async def close(self) -> None:
        if self._resource_ctx:
            await self._resource_ctx.__aexit__(None, None, None)
            self._resource_ctx = None
            self._resource = None
            self._table = None
            logger.info("DynamoDB resource closed")

    # -- Posts ---------------------------------------------------------------

    async def list_posts(self, page: int, page_size: int) -> tuple[list[dict], int]:
        resp = await self._table.query(
            IndexName="GSI1",
            KeyConditionExpression="GSI1PK = :pk",
            ExpressionAttributeValues={":pk": "POSTS"},
            ScanIndexForward=False,
        )
        all_items = resp.get("Items", [])
        total = len(all_items)

        offset = (page - 1) * page_size
        page_items = all_items[offset : offset + page_size]
        return [_item_to_post(item) for item in page_items], total

    async def get_post(self, post_id: int) -> dict:
        resp = await self._table.get_item(
            Key={"PK": f"POST#{post_id}", "SK": "META"}
        )
        item = resp.get("Item")
        if item is None:
            raise PostNotFoundError("Post not found")
        return _item_to_post(item)

    async def get_post_comments(self, post_id: int) -> list[dict]:
        resp = await self._table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
            ExpressionAttributeValues={
                ":pk": f"POST#{post_id}",
                ":prefix": "COMMENT#",
            },
        )
        items = sorted(resp.get("Items", []), key=lambda x: x["created_at"])
        return [_item_to_comment(item) for item in items]

    async def create_post(self, author: str, body: str) -> dict:
        post_id = await _next_id(self._table)
        now = _now_iso()
        item = {
            "PK": f"POST#{post_id}",
            "SK": "META",
            "GSI1PK": "POSTS",
            "GSI1SK": now,
            "id": post_id,
            "author": author,
            "body": body,
            "thumbs_up": 0,
            "thumbs_down": 0,
            "comment_count": 0,
            "created_at": now,
        }
        await self._table.put_item(Item=item)
        return _item_to_post(item)

    async def delete_post(self, post_id: int, user: str) -> None:
        post = await self.get_post(post_id)
        if post["author"] != user:
            raise OwnershipError("Not your post")

        # Delete all comments for this post
        comments = await self.get_post_comments(post_id)
        for c in comments:
            await self._table.delete_item(
                Key={"PK": f"POST#{post_id}", "SK": f"COMMENT#{c['id']}"}
            )

        # Delete thumbs for the post
        await self._delete_thumbs_for(post_id)

        # Delete the post itself
        await self._table.delete_item(
            Key={"PK": f"POST#{post_id}", "SK": "META"}
        )

    # -- Comments ------------------------------------------------------------

    async def create_comment(
        self, post_id: int, author: str, body: str, parent_id: int | None = None
    ) -> dict:
        await self.get_post(post_id)

        if parent_id is not None:
            resp = await self._table.get_item(
                Key={"PK": f"POST#{post_id}", "SK": f"COMMENT#{parent_id}"}
            )
            parent = resp.get("Item")
            if parent is None:
                raise CommentNotFoundError("Parent comment not found")
            if parent.get("parent_id"):
                raise NestingDepthError("Cannot reply to a reply (max 1-depth nesting)")

        comment_id = await _next_id(self._table)
        now = _now_iso()
        item = {
            "PK": f"POST#{post_id}",
            "SK": f"COMMENT#{comment_id}",
            "id": comment_id,
            "post_id": post_id,
            "author": author,
            "body": body,
            "created_at": now,
        }
        if parent_id is not None:
            item["parent_id"] = parent_id

        await self._table.put_item(Item=item)

        # Increment comment_count on the post
        await self._table.update_item(
            Key={"PK": f"POST#{post_id}", "SK": "META"},
            UpdateExpression="SET comment_count = if_not_exists(comment_count, :zero) + :inc",
            ExpressionAttributeValues={":zero": 0, ":inc": 1},
        )

        return _item_to_comment(item)

    # -- Thumbs (posts only) -------------------------------------------------

    async def toggle_thumb(self, post_id: int, voter: str, direction: int) -> dict:
        thumb_pk = f"THUMB#POST#{post_id}"
        thumb_sk = f"VOTER#{voter}"

        resp = await self._table.get_item(
            Key={"PK": f"POST#{post_id}", "SK": "META"}
        )
        if not resp.get("Item"):
            raise PostNotFoundError("Post not found")

        # Check existing thumb
        resp = await self._table.get_item(Key={"PK": thumb_pk, "SK": thumb_sk})
        existing = resp.get("Item")

        if existing and _decimal_to_int(existing["direction"]) == direction:
            await self._table.delete_item(Key={"PK": thumb_pk, "SK": thumb_sk})
            up_delta = -1 if direction == 1 else 0
            down_delta = -1 if direction == -1 else 0
        elif existing:
            await self._table.put_item(
                Item={"PK": thumb_pk, "SK": thumb_sk, "direction": direction, "voter": voter}
            )
            up_delta = 1 if direction == 1 else -1
            down_delta = 1 if direction == -1 else -1
        else:
            await self._table.put_item(
                Item={"PK": thumb_pk, "SK": thumb_sk, "direction": direction, "voter": voter}
            )
            up_delta = 1 if direction == 1 else 0
            down_delta = 1 if direction == -1 else 0

        resp = await self._table.update_item(
            Key={"PK": f"POST#{post_id}", "SK": "META"},
            UpdateExpression="SET thumbs_up = if_not_exists(thumbs_up, :zero) + :up, thumbs_down = if_not_exists(thumbs_down, :zero) + :down",
            ExpressionAttributeValues={":up": up_delta, ":down": down_delta, ":zero": 0},
            ReturnValues="ALL_NEW",
        )
        updated = resp["Attributes"]
        return {
            "thumbs_up": _decimal_to_int(updated["thumbs_up"]),
            "thumbs_down": _decimal_to_int(updated["thumbs_down"]),
        }

    # -- Internal helpers ----------------------------------------------------

    async def _delete_thumbs_for(self, post_id: int) -> None:
        """Delete all thumb records for a post."""
        thumb_pk = f"THUMB#POST#{post_id}"
        resp = await self._table.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": thumb_pk},
        )
        for item in resp.get("Items", []):
            await self._table.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
