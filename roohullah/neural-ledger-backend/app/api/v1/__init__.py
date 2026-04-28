from fastapi import APIRouter
from app.api.v1 import auth, orgs, ingest, transactions

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(orgs.router)
api_router.include_router(ingest.router)
api_router.include_router(transactions.router)
