"""
LandVerify — FastAPI Application
The complete, runnable backend for LandVerify MVP.

Start with:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

API Docs:
    http://localhost:8000/docs
"""
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers.verification import router as verification_router
from app.routers.auth import router as auth_router
from app.routers.alerts import router as alerts_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
settings = get_settings()

# ── App ────────────────────────────────────────────────────────────
app = FastAPI(
    title="LandVerify API",
    description="""
## 🏛️ LandVerify — Nigeria's Land Trust Layer

AI-powered land document verification. Eliminates fraud. Protects buyers.

### Endpoints
- **POST /api/v1/verify** — Full document verification (OCR + Claude AI + Trust Score)
- **POST /api/v1/auth/register** — Create account
- **POST /api/v1/auth/login** — Sign in
- **GET  /api/v1/auth/me** — Current user
- **GET  /api/v1/dashboard** — Portfolio stats
- **GET  /api/v1/alerts** — Fraud alerts
- **GET  /health** — System health
""",
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS — open for local dev, lock down in production ────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Restrict to your domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global error handler — never expose tracebacks ────────────────
@app.exception_handler(Exception)
async def global_error(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.method} {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error",
                 "message": "An unexpected error occurred. Our team has been notified."}
    )

@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": _code(exc.status_code), "message": exc.detail}
    )

def _code(s):
    return {401:"unauthorized",403:"forbidden",404:"not_found",
            409:"conflict",422:"validation_error",429:"rate_limited",
            500:"internal_server_error"}.get(s, f"error_{s}")

# ── Routes ─────────────────────────────────────────────────────────
app.include_router(verification_router)
app.include_router(auth_router)
app.include_router(alerts_router)


# ── Health ─────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {
        "service": "LandVerify API",
        "version": settings.app_version,
        "status": "operational",
        "docs": "/docs",
        "message": "Nigeria's Land Trust Layer — Eliminating Property Fraud with AI",
    }

@app.get("/health", tags=["Health"])
async def health():
    from app.database import check_db_connection
    db_ok = await check_db_connection()
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "unreachable (start PostgreSQL or verification still works in demo mode)",
        "ai_model": settings.claude_model,
        "environment": "development" if settings.debug else "production",
    }


# ── Startup ────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info("=" * 55)
    logger.info("  LandVerify API  —  Starting Up")
    logger.info(f"  Version : {settings.app_version}")
    logger.info(f"  Model   : {settings.claude_model}")
    logger.info(f"  Debug   : {settings.debug}")
    logger.info(f"  Docs    : http://localhost:8000/docs")
    logger.info("=" * 55)

    # Try to init DB tables (fails gracefully if no PostgreSQL)
    if settings.debug:
        try:
            from app.database import init_db
            await init_db()
            logger.info("  ✅ Database tables ready")
        except Exception as e:
            logger.warning(f"  ⚠️  DB not available ({e}) — verification still works in demo mode")

@app.on_event("shutdown")
async def shutdown():
    logger.info("LandVerify API — Shutting Down")
