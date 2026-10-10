"""Deals fund follow endpoints (HarkPro/08-tab-deals.md §5.3-4). User data in the user DB (App/services/deals_follow).

  GET    /api/v2/deals/follows            followed houses (house key, display name, added_at)
  POST   /api/v2/deals/follows            {house, name?} -> follow (idempotent); returns the list
  DELETE /api/v2/deals/follows?house=…    unfollow (idempotent); returns the list
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from App.api.v2 import models as m
from App.api.v2.routes import V2Route, _user_call, envelope
from App.services import deals_follow
from App.services.common import Result

router = APIRouter(route_class=V2Route, tags=["deals-tab"])


class FollowedHouse(BaseModel):
    model_config = ConfigDict(extra="allow")
    house: str
    name: str
    added_at: Optional[datetime] = None


class FollowPost(BaseModel):
    model_config = ConfigDict(extra="forbid")
    house: str = Field(..., min_length=1, max_length=deals_follow.MAX_NAME_CHARS)
    name: Optional[str] = Field(None, max_length=deals_follow.MAX_NAME_CHARS)


def _env(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return envelope(Result(as_of=None, rows=rows, sources=[deals_follow.TABLE]), strict=False)


@router.get("/deals/follows", response_model=m.Envelope[FollowedHouse],
            description="Followed deal houses (user DB). Telegram alerts on them only per the 08-tab-deals rule.")
def follows_get() -> dict[str, Any]:
    return _env(_user_call(deals_follow.list_follows))


@router.post("/deals/follows", response_model=m.Envelope[FollowedHouse],
             description="Follow a house (keyed like the Deals tab's house key). Idempotent; returns the list.")
def follows_post(body: FollowPost) -> dict[str, Any]:
    return _env(_user_call(deals_follow.add_follow, body.house, body.name))


@router.delete("/deals/follows", response_model=m.Envelope[FollowedHouse],
               description="Unfollow a house. Idempotent; returns the list.")
def follows_delete(house: str = Query(..., min_length=1, max_length=deals_follow.MAX_NAME_CHARS)) -> dict[str, Any]:
    return _env(_user_call(deals_follow.remove_follow, house))
