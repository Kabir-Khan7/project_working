"""
schemas/org.py
--------------
Pydantic v2 schemas for Organisation + OrgMember endpoints.
"""

import re
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator


# ── Org create / update ───────────────────────────────────────────────────────
class OrgCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: Optional[str] = Field(None, min_length=2, max_length=100)
    industry: Optional[str] = None
    country: str = "PK"
    currency: str = "PKR"

    @field_validator("slug", mode="before")
    @classmethod
    def auto_slug(cls, v: Optional[str], info) -> str:
        if v:
            return re.sub(r"[^a-z0-9-]", "", v.lower().replace(" ", "-"))
        # auto-generate from name if not provided
        name = info.data.get("name", "org")
        return re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-"))[:50]


class OrgUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    industry: Optional[str] = None
    country: Optional[str] = None
    currency: Optional[str] = None


class OrgResponse(BaseModel):
    id: str
    name: str
    slug: str
    industry: Optional[str]
    country: str
    currency: str
    plan: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Member management ─────────────────────────────────────────────────────────
class InviteMemberRequest(BaseModel):
    email: str
    role: str = Field("member", pattern="^(admin|member|viewer)$")


class MemberResponse(BaseModel):
    id: str
    user_id: str
    org_id: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgWithMembersResponse(OrgResponse):
    members: List[MemberResponse] = []
