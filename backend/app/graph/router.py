"""HTTP surface for the knowledge graph (entities + 1-hop neighbours)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.models import User
from app.graph.neo4j_client import (
    list_relationships_for_entity,
    list_user_entities,
)

router = APIRouter(prefix="/graph", tags=["graph"])

CurrentUserDep = Annotated[User, Depends(get_current_user)]


class EntityItem(BaseModel):
    name: str
    type: str | None = None
    description: str | None = None
    document_ids: list[str] = []


class EntityListResponse(BaseModel):
    items: list[EntityItem]
    total: int


class NeighbourItem(BaseModel):
    source: str
    target: str
    relation: str
    target_type: str | None = None
    target_description: str | None = None


class NeighbourListResponse(BaseModel):
    items: list[NeighbourItem]


@router.get("/entities", response_model=EntityListResponse)
async def list_entities(
    current_user: CurrentUserDep,
    limit: int = Query(default=200, ge=1, le=1000),
) -> EntityListResponse:
    rows = await list_user_entities(str(current_user.id), limit=limit)
    items = [
        EntityItem(
            name=row["name"],
            type=row.get("type"),
            description=row.get("description"),
            document_ids=list(row.get("document_ids") or []),
        )
        for row in rows
    ]
    return EntityListResponse(items=items, total=len(items))


@router.get("/entities/{name}/neighbours", response_model=NeighbourListResponse)
async def list_neighbours(
    name: str,
    current_user: CurrentUserDep,
    limit: int = Query(default=50, ge=1, le=500),
) -> NeighbourListResponse:
    rows = await list_relationships_for_entity(str(current_user.id), name, limit=limit)
    items = [
        NeighbourItem(
            source=row["source"],
            target=row["target"],
            relation=row["relation"],
            target_type=row.get("target_type"),
            target_description=row.get("target_description"),
        )
        for row in rows
    ]
    return NeighbourListResponse(items=items)
