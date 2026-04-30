from fastapi import APIRouter

from src.api.analysis_results import router as analysis_results_router
from src.api.health import router as health_router
from src.api.pipeline import router as pipeline_router
from src.api.product_experience_reports import (
    router as product_experience_reports_router,
)
from src.api.source_items import router as source_items_router
from src.api.stats import router as stats_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(source_items_router)
api_router.include_router(analysis_results_router)
api_router.include_router(product_experience_reports_router)
api_router.include_router(stats_router)
api_router.include_router(pipeline_router)
