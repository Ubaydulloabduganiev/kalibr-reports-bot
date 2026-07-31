from fastapi import APIRouter

from app.api import activation, auth, configuration, entities, reports

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(entities.router)
api_router.include_router(activation.router)
api_router.include_router(configuration.router)
api_router.include_router(reports.router)
