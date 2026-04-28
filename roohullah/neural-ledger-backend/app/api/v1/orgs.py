"""
api/v1/orgs.py
--------------
Routes:
  POST   /api/v1/orgs                    → create org (creator becomes admin)
  GET    /api/v1/orgs                    → list my orgs
  GET    /api/v1/orgs/{org_id}           → get org detail
  PATCH  /api/v1/orgs/{org_id}           → update org (admin only)
  DELETE /api/v1/orgs/{org_id}           → soft-delete org (admin only)
  POST   /api/v1/orgs/{org_id}/members   → invite member (admin only)
  GET    /api/v1/orgs/{org_id}/members   → list members
  DELETE /api/v1/orgs/{org_id}/members/{user_id} → remove member (admin only)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.dependencies import CurrentUser, DBSession, require_org_member
from app.models.org import OrgMember, Organisation
from app.models.user import User
from app.services.seed_coa import seed_chart_of_accounts
from app.schemas.org import (
    InviteMemberRequest,
    MemberResponse,
    OrgCreateRequest,
    OrgResponse,
    OrgUpdateRequest,
    OrgWithMembersResponse,
)

router = APIRouter(prefix="/orgs", tags=["Organisations"])


# ── Create org ────────────────────────────────────────────────────────────────
@router.post("", response_model=OrgResponse, status_code=201)
async def create_org(payload: OrgCreateRequest, user: CurrentUser, db: DBSession):
    # Check slug uniqueness
    existing = await db.execute(
        select(Organisation).where(Organisation.slug == payload.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, detail="Slug already taken. Choose another.")

    org = Organisation(**payload.model_dump())
    db.add(org)
    await db.flush()  # get org.id before adding member

    # Creator becomes admin
    member = OrgMember(org_id=org.id, user_id=user.id, role="admin")
    db.add(member)
    await db.commit()
    await db.refresh(org)

    # Seed default Pakistani SME Chart of Accounts
    await seed_chart_of_accounts(db, org.id)

    return org


# ── List my orgs ──────────────────────────────────────────────────────────────
@router.get("", response_model=list[OrgResponse])
async def list_my_orgs(user: CurrentUser, db: DBSession):
    result = await db.execute(
        select(Organisation)
        .join(OrgMember, OrgMember.org_id == Organisation.id)
        .where(OrgMember.user_id == user.id, OrgMember.is_active == True)
    )
    return result.scalars().all()


# ── Get single org ────────────────────────────────────────────────────────────
@router.get("/{org_id}", response_model=OrgWithMembersResponse)
async def get_org(
    org_id: str,
    user: CurrentUser,
    db: DBSession,
    _=Depends(require_org_member("viewer")),
):
    org = await db.get(Organisation, org_id)
    if not org:
        raise HTTPException(404, detail="Organisation not found")
    return org


# ── Update org ────────────────────────────────────────────────────────────────
@router.patch("/{org_id}", response_model=OrgResponse)
async def update_org(
    org_id: str,
    payload: OrgUpdateRequest,
    user: CurrentUser,
    db: DBSession,
    _=Depends(require_org_member("admin")),
):
    org = await db.get(Organisation, org_id)
    if not org:
        raise HTTPException(404, detail="Organisation not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(org, field, value)
    await db.commit()
    await db.refresh(org)
    return org


# ── Soft-delete org ───────────────────────────────────────────────────────────
@router.delete("/{org_id}", status_code=204)
async def delete_org(
    org_id: str,
    user: CurrentUser,
    db: DBSession,
    _=Depends(require_org_member("admin")),
):
    org = await db.get(Organisation, org_id)
    if not org:
        raise HTTPException(404, detail="Organisation not found")
    org.is_active = False
    await db.commit()


# ── Invite member ─────────────────────────────────────────────────────────────
@router.post("/{org_id}/members", response_model=MemberResponse, status_code=201)
async def invite_member(
    org_id: str,
    payload: InviteMemberRequest,
    user: CurrentUser,
    db: DBSession,
    _=Depends(require_org_member("admin")),
):
    # Find user by email
    result = await db.execute(select(User).where(User.email == payload.email.lower()))
    invitee = result.scalar_one_or_none()
    if not invitee:
        raise HTTPException(404, detail="No account found for that email")

    # Check if already a member
    existing = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id, OrgMember.user_id == invitee.id
        )
    )
    member = existing.scalar_one_or_none()
    if member:
        if member.is_active:
            raise HTTPException(409, detail="User is already a member")
        # Re-activate
        member.is_active = True
        member.role = payload.role
    else:
        member = OrgMember(org_id=org_id, user_id=invitee.id, role=payload.role)
        db.add(member)

    await db.commit()
    await db.refresh(member)
    return member


# ── List members ──────────────────────────────────────────────────────────────
@router.get("/{org_id}/members", response_model=list[MemberResponse])
async def list_members(
    org_id: str,
    user: CurrentUser,
    db: DBSession,
    _=Depends(require_org_member("viewer")),
):
    result = await db.execute(
        select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.is_active == True)
    )
    return result.scalars().all()


# ── Remove member ─────────────────────────────────────────────────────────────
@router.delete("/{org_id}/members/{target_user_id}", status_code=204)
async def remove_member(
    org_id: str,
    target_user_id: str,
    user: CurrentUser,
    db: DBSession,
    _=Depends(require_org_member("admin")),
):
    result = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == target_user_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(404, detail="Member not found")

    member.is_active = False
    await db.commit()
