"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

from fastapi import APIRouter

import auth

router = APIRouter()


@router.get("/health")
def health():
    return {"ok": True, "auth_required": auth.AUTH_ENABLED}
