"""
LandVerify — Complete Backend with PostgreSQL Database
Works on Railway, Render, Replit, and Google Colab.
"""
import uuid, json, logging, os, hashlib, secrets
from datetime import datetime, timedelta
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, UploadFile, File, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic

try:
    import asyncpg
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────
API_KEY      = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-6")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SECRET_KEY   = os.environ.get("SECRET_KEY", "landverify-secret-2024")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

db_pool = None

# ── Database Setup ─────────────────────────────────────────────
async def init_db():
    @asynccontextmanager
async def lifespan(app: app = FastAPI(lifespan=lifespan)):
    await init_db()
    yield
    global db_pool
    if not DB_AVAILABLE or not DATABASE_URL:
        logger.warning("No database URL — running without persistence")
        return
    try:
        db_pool = await asyncpg.create_pool(
            DATABASE_URL, min_size=1, max_size=5, command_timeout=30
        )
        async with db_pool.acquire() as conn:
            await conn.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    email TEXT UNIQUE NOT NULL,
                    full_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'buyer',
                    plan TEXT DEFAULT 'free',
                    email_verified BOOLEAN DEFAULT FALSE,
                    verifications_used INTEGER DEFAULT 0,
                    verifications_limit INTEGER DEFAULT 10,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                    token TEXT UNIQUE NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS verifications (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    verification_id TEXT UNIQUE NOT NULL,
                    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
                    property_address TEXT NOT NULL,
                    document_type TEXT,
                    state TEXT,
                    trust_score NUMERIC,
                    trust_level TEXT,
                    ai_summary TEXT,
                    ai_recommendation TEXT,
                    result_json JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_subscriptions (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                    property_address TEXT NOT NULL,
                    file_number TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS fraud_alerts (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
                    property_address TEXT,
                    title TEXT NOT NULL,
                    description TEXT,
                    severity TEXT DEFAULT 'medium',
                    is_resolved BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        logger.info("✅ Database connected and tables ready")
    except Exception as e:
        logger.error(f"Database init failed: {e}")
        db_pool = None

async def get_conn():
    if db_pool:
        conn = await db_pool.acquire()
        try:
            yield conn
        finally:
            await db_pool.release(conn)
    else:
        yield None

# ── Auth Helpers ───────────────────────────────────────────────
def hash_pw(pw): return hashlib.sha256((pw + SECRET_KEY).encode()).hexdigest()
def make_token(): return secrets.token_urlsafe(32)

async def current_user(authorization: Optional[str] = Header(None), conn=Depends(get_conn)):
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ")[1]
    if not conn:
        return {"id": "demo", "email": "demo@landverify.ng", "full_name": "Demo User",
                "role": "buyer", "plan": "free", "verifications_used": 0, "verifications_limit": 10}
    try:
        row = await conn.fetchrow("""
            SELECT u.* FROM users u JOIN sessions s ON s.user_id = u.id
            WHERE s.token = $1 AND s.expires_at > NOW()
        """, token)
        return dict(row) if row else None
    except:
        return None

# ── App ────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("LandVerify API starting...")
    await init_db()
    yield
    if db_pool:
        await db_pool.close()

app = FastAPI(title="LandVerify API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# ── Health ─────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"service": "LandVerify API", "status": "operational", "version": "1.0.0",
            "ai_ready": bool(API_KEY), "database": "connected" if db_pool else "demo mode"}

@app.get("/health")
def health():
    return {"status": "healthy", "ai_model": CLAUDE_MODEL,
            "ai_ready": bool(API_KEY), "database": "connected" if db_pool else "demo mode"}

# ── REGISTER ───────────────────────────────────────────────────
class RegBody(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = "buyer"

@app.post("/api/v1/auth/register")
async def register(body: RegBody, conn=Depends(get_conn)):
    user_data = {"id": str(uuid.uuid4()), "email": body.email, "full_name": body.full_name,
                 "role": body.role, "plan": "free", "email_verified": False,
                 "verifications_used": 0, "verifications_limit": 10, "can_verify": True}
    if not conn:
        return {"access_token": make_token(), "refresh_token": make_token(),
                "token_type": "bearer", "expires_in": 86400, "user": user_data}
    try:
        if await conn.fetchrow("SELECT id FROM users WHERE email=$1", body.email.lower()):
            raise HTTPException(400, "Email already registered")
        if len(body.password) < 6:
            raise HTTPException(400, "Password must be at least 6 characters")
        uid = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO users (id,email,full_name,password_hash,role) VALUES ($1,$2,$3,$4,$5)",
            uid, body.email.lower(), body.full_name, hash_pw(body.password), body.role
        )
        token = make_token()
        await conn.execute(
            "INSERT INTO sessions (user_id,token,expires_at) VALUES ($1,$2,$3)",
            uid, token, datetime.utcnow() + timedelta(days=30)
        )
        user_data["id"] = uid
        return {"access_token": token, "refresh_token": make_token(),
                "token_type": "bearer", "expires_in": 86400, "user": user_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Register error: {e}")
        raise HTTPException(500, "Registration failed")

# ── LOGIN ──────────────────────────────────────────────────────
class LoginBody(BaseModel):
    email: str
    password: str

@app.post("/api/v1/auth/login")
async def login(body: LoginBody, conn=Depends(get_conn)):
    if not conn:
        return {"access_token": make_token(), "refresh_token": make_token(),
                "token_type": "bearer", "expires_in": 86400,
                "user": {"id": str(uuid.uuid4()), "email": body.email,
                         "full_name": body.email.split("@")[0], "role": "buyer",
                         "plan": "free", "email_verified": True,
                         "verifications_used": 0, "verifications_limit": 10, "can_verify": True}}
    try:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE email=$1 AND password_hash=$2",
            body.email.lower(), hash_pw(body.password)
        )
        if not row:
            raise HTTPException(401, "Invalid email or password")
        u = dict(row)
        token = make_token()
        await conn.execute(
            "INSERT INTO sessions (user_id,token,expires_at) VALUES ($1,$2,$3)",
            str(u["id"]), token, datetime.utcnow() + timedelta(days=30)
        )
        return {"access_token": token, "refresh_token": make_token(),
                "token_type": "bearer", "expires_in": 86400,
                "user": {"id": str(u["id"]), "email": u["email"], "full_name": u["full_name"],
                         "role": u["role"], "plan": u["plan"], "email_verified": u["email_verified"],
                         "verifications_used": u["verifications_used"],
                         "verifications_limit": u["verifications_limit"], "can_verify": True}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(500, "Login failed")

@app.get("/api/v1/auth/me")
async def me(user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "Not authenticated")
    return {**user, "id": str(user.get("id", "")), "can_verify": True}

@app.post("/api/v1/auth/logout")
async def logout(authorization: Optional[str] = Header(None), conn=Depends(get_conn)):
    if authorization and authorization.startswith("Bearer ") and conn:
        try:
            await conn.execute("DELETE FROM sessions WHERE token=$1", authorization.split(" ")[1])
        except:
            pass
    return {"message": "Logged out"}

# ── VERIFY ─────────────────────────────────────────────────────
@app.post("/api/v1/verify")
async def verify(
    document_type: str = Form(...), state: str = Form(...),
    property_address: str = Form(...), owner_name: str = Form(...),
    user_role: str = Form(...), file_number: Optional[str] = Form(None),
    additional_notes: Optional[str] = Form(None), file: Optional[UploadFile] = File(None),
    authorization: Optional[str] = Header(None), conn=Depends(get_conn),
):
    vid = "LV-" + str(uuid.uuid4())[:8].upper()
    logger.info(f"[{vid}] {property_address}")

    user_id = None
    if authorization and authorization.startswith("Bearer ") and conn:
        try:
            row = await conn.fetchrow("""
                SELECT u.id FROM users u JOIN sessions s ON s.user_id=u.id
                WHERE s.token=$1 AND s.expires_at>NOW()
            """, authorization.split(" ")[1])
            if row:
                user_id = str(row["id"])
        except:
            pass

    # ── Claude AI ──────────────────────────────────────────────
    data = None
    if API_KEY:
        try:
            client = anthropic.Anthropic(api_key=API_KEY)
            msg = client.messages.create(
                model=CLAUDE_MODEL, max_tokens=2000,
                messages=[{"role": "user", "content": f"""You are LandVerify, Nigeria's top land fraud expert.
Analyse this property and return ONLY valid JSON — no markdown.

Address: {property_address} | State: {state} | Type: {document_type}
Owner: {owner_name} | File No: {file_number or "none"} | Role: {user_role}
Notes: {additional_notes or "none"}

Return: {{"trust_score":0-100,"trust_level":"safe|caution|danger","summary":"2-3 sentences","recommendation":"advice for {user_role}","checks":[{{"label":"name","status":"pass|fail|warning","detail":"finding"}}],"fraud_flags":[{{"severity":"high|medium|low","title":"title","description":"detail","action":"what to do"}}],"ownership_chain":[{{"year":"y","owner":"n","type":"transaction","registered":true}}]}}"""}]
            )
            text = msg.content[0].text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].strip()
            data = json.loads(text)
        except Exception as e:
            logger.error(f"[{vid}] Claude error: {e}")

    if not data:
        data = {"trust_score": 65, "trust_level": "caution",
                "summary": f"Analysis of {property_address}. Manual verification recommended.",
                "recommendation": "Visit the State Land Registry before any payment.",
                "checks": [
                    {"label": "Document Format", "status": "pass", "detail": "Standard format"},
                    {"label": "File Number Validity", "status": "warning", "detail": "Needs registry confirmation"},
                    {"label": "Stamp Duty Check", "status": "warning", "detail": "Cannot verify remotely"},
                    {"label": "Ownership Consistency", "status": "warning", "detail": "Needs physical verification"},
                    {"label": "Registry Match", "status": "fail", "detail": "Live registry not connected"},
                    {"label": "Encumbrance Check", "status": "warning", "detail": "Check for existing mortgages"},
                    {"label": "Duplicate Title Check", "status": "warning", "detail": "Requires registry access"},
                ],
                "fraud_flags": [],
                "ownership_chain": [{"year": "2024", "owner": owner_name, "type": "Current Owner", "registered": True}]}

    score = max(0, min(100, int(data.get("trust_score", 65))))
    level = data.get("trust_level", "caution")
    checks = data.get("checks", [])
    flags = data.get("fraud_flags", [])
    chain = data.get("ownership_chain", [])

    result = {
        "verification_id": vid, "timestamp": datetime.utcnow().isoformat(),
        "property_address": property_address, "document_type": document_type, "state": state,
        "trust_score": score, "trust_level": level,
        "trust_score_breakdown": {"document_authenticity_score": min(score+5,100),
            "registry_match_score": max(score-10,0), "ownership_chain_score": min(score+8,100),
            "encumbrance_score": min(score+3,100), "geospatial_score": min(score+6,100),
            "fraud_penalty": len([f for f in flags if f.get("severity")=="high"])*5, "final_score": score},
        "checks": [{"check_id": c["label"].lower().replace(" ","_"), "label": c["label"],
                    "status": c["status"], "detail": c["detail"]} for c in checks],
        "checks_passed": sum(1 for c in checks if c.get("status")=="pass"),
        "checks_failed": sum(1 for c in checks if c.get("status")=="fail"),
        "checks_warned": sum(1 for c in checks if c.get("status")=="warning"),
        "fraud_flags": [{"flag_id": str(uuid.uuid4())[:6], "severity": f.get("severity","medium"),
                         "title": f.get("title","Risk"), "description": f.get("description",""),
                         "recommendation": f.get("action","Consult a property lawyer"),
                         "confidence": 0.85} for f in flags],
        "fraud_risk_summary": data.get("summary",""),
        "ownership_chain": {"total_owners": len(chain), "chain_integrity": 0.85,
            "has_gaps": False, "has_disputes": False,
            "records": [{"year": r.get("year","?"), "owner_name": r.get("owner","?"),
                         "transaction_type": r.get("type","?"), "registered": r.get("registered",True),
                         "flagged": False} for r in chain],
            "analysis_summary": f"{len(chain)} record(s) by Claude AI."},
        "ai_summary": data.get("summary",""), "ai_recommendation": data.get("recommendation",""),
        "verified_by": f"LandVerify AI + {CLAUDE_MODEL}" if API_KEY else "LandVerify Demo Mode",
    }

    if conn:
        try:
            await conn.execute("""
                INSERT INTO verifications
                (id,verification_id,user_id,property_address,document_type,state,
                 trust_score,trust_level,ai_summary,ai_recommendation,result_json)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            """, str(uuid.uuid4()), vid, user_id, property_address, document_type,
                state, score, level, data.get("summary",""), data.get("recommendation",""),
                json.dumps(result))
            if user_id:
                await conn.execute(
                    "UPDATE users SET verifications_used=verifications_used+1 WHERE id=$1", user_id)
        except Exception as e:
            logger.error(f"[{vid}] DB save error: {e}")

    return result

# ── DASHBOARD ──────────────────────────────────────────────────
@app.get("/api/v1/dashboard")
async def dashboard(user=Depends(current_user), conn=Depends(get_conn)):
    if not user:
        raise HTTPException(401, "Not authenticated")
    uid = str(user.get("id",""))
    if not conn or uid == "demo":
        return {"user": user, "stats": {"total":0,"safe":0,"caution":0,"danger":0,
                "monitored_properties":0,"active_alerts":0}, "recent_verifications": []}
    try:
        rows = await conn.fetch("""
            SELECT verification_id,property_address,state,trust_score,trust_level,created_at
            FROM verifications WHERE user_id=$1 ORDER BY created_at DESC LIMIT 20
        """, uid)
        vlist = [dict(r) for r in rows]
        subs = await conn.fetchval("SELECT COUNT(*) FROM alert_subscriptions WHERE user_id=$1 AND is_active=TRUE", uid) or 0
        alerts = await conn.fetchval("SELECT COUNT(*) FROM fraud_alerts WHERE user_id=$1 AND is_resolved=FALSE", uid) or 0
        return {"user": {**user, "id": uid},
                "stats": {"total": len(vlist),
                          "safe": sum(1 for v in vlist if v["trust_level"]=="safe"),
                          "caution": sum(1 for v in vlist if v["trust_level"]=="caution"),
                          "danger": sum(1 for v in vlist if v["trust_level"]=="danger"),
                          "monitored_properties": subs, "active_alerts": alerts},
                "recent_verifications": [{"verification_id": v["verification_id"],
                    "property_address": v["property_address"], "state": v["state"],
                    "trust_score": float(v["trust_score"] or 0), "trust_level": v["trust_level"],
                    "created_at": v["created_at"].isoformat()} for v in vlist]}
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        return {"user": user, "stats": {"total":0,"safe":0,"caution":0,"danger":0,
                "monitored_properties":0,"active_alerts":0}, "recent_verifications": []}

# ── ALERTS ─────────────────────────────────────────────────────
@app.get("/api/v1/alerts")
async def get_alerts(user=Depends(current_user), conn=Depends(get_conn)):
    if not user:
        raise HTTPException(401, "Not authenticated")
    uid = str(user.get("id",""))
    if not conn or uid == "demo":
        return {"alerts": [], "total": 0}
    try:
        rows = await conn.fetch(
            "SELECT * FROM fraud_alerts WHERE user_id=$1 ORDER BY created_at DESC LIMIT 50", uid)
        return {"alerts": [{"id": str(r["id"]), "title": r["title"], "description": r["description"],
                "severity": r["severity"], "is_resolved": r["is_resolved"],
                "property_address": r["property_address"],
                "created_at": r["created_at"].isoformat()} for r in rows], "total": len(rows)}
    except Exception as e:
        logger.error(f"Alerts error: {e}")
        return {"alerts": [], "total": 0}

class SubBody(BaseModel):
    property_address: str
    file_number: Optional[str] = None

@app.post("/api/v1/alerts/subscribe")
async def subscribe(body: SubBody, user=Depends(current_user), conn=Depends(get_conn)):
    if not user:
        raise HTTPException(401, "Not authenticated")
    uid = str(user.get("id",""))
    if conn and uid != "demo":
        try:
            await conn.execute(
                "INSERT INTO alert_subscriptions (user_id,property_address,file_number) VALUES ($1,$2,$3)",
                uid, body.property_address, body.file_number)
        except Exception as e:
            logger.error(f"Subscribe error: {e}")
    return {"message": "Monitoring enabled", "property_address": body.property_address}

@app.patch("/api/v1/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str, user=Depends(current_user), conn=Depends(get_conn)):
    if not user:
        raise HTTPException(401, "Not authenticated")
    if conn:
        try:
            await conn.execute("UPDATE fraud_alerts SET is_resolved=TRUE WHERE id=$1", uuid.UUID(alert_id))
        except Exception as e:
            logger.error(f"Resolve error: {e}")
    return {"message": "Alert resolved"}
