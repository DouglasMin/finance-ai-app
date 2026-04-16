"""Single-table DynamoDB helper.

Phase-forward: schema supports future POSITION#, ORDER#, STRATEGY# SKs under
the same USER# PK — see spec section 6.
"""
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key


def _convert_floats(obj: Any) -> Any:
    """Recursively convert float → Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _convert_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_floats(i) for i in obj]
    return obj

TABLE_NAME = os.environ.get("DDB_TABLE", "financial-bot")
USER_PK = "USER#me"

_table = None


def get_table():
    global _table
    if _table is None:
        region = os.environ.get("AWS_REGION", "ap-northeast-2")
        dynamodb = boto3.resource("dynamodb", region_name=region)
        _table = dynamodb.Table(TABLE_NAME)
    return _table


def put_item(sk: str, attrs: dict) -> None:
    item = _convert_floats({
        "PK": USER_PK,
        "SK": sk,
        **attrs,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    get_table().put_item(Item=item)


def get_item(sk: str) -> Optional[dict]:
    response = get_table().get_item(Key={"PK": USER_PK, "SK": sk})
    return response.get("Item")


def query_by_sk_prefix(
    prefix: str, limit: Optional[int] = None, ascending: bool = True
) -> list[dict]:
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("PK").eq(USER_PK) & Key("SK").begins_with(prefix),
        "ScanIndexForward": ascending,
    }
    if limit is not None:
        kwargs["Limit"] = limit
    response = get_table().query(**kwargs)
    return response.get("Items", [])


def delete_item(sk: str) -> None:
    get_table().delete_item(Key={"PK": USER_PK, "SK": sk})
