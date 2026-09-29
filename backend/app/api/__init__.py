from fastapi import APIRouter
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.file import router as file_router
from app.api.lab import router as lab_router
from app.api.user import router as user_router

api = APIRouter(prefix="/api")

api.include_router(admin_router)
api.include_router(auth_router)
api.include_router(file_router)
api.include_router(lab_router)
api.include_router(user_router)
