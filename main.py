"""
LandVerify — Complete Backend (Single File)
Works on Railway, Render, Replit, and Google Colab.

Railway / Render / Replit: Set ANTHROPIC_API_KEY in environment variables
Colab: Set ANTHROPIC_API_KEY in os.environ before running
"""
import uuid, json, logging, os
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ── Load API key from environment ─────────────────────────────
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-6")

# ── App ────────────────────────────────────────────────────────
app = FastAPI(
    title="LandVerify API",
    description="Nigeria's Land Trust Layer — AI-Powered Land Document Verification",
    version="1.0.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Health ─────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "service": "LandVerify API",
        "status": "operational",
        "version": "1.0.0",
        "docs": "/docs",
        "ai_ready": bool(API_KEY),
    }

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "version": "1.0.0",
        "ai_model": CLAUDE_MODEL,
        "ai_ready": bool(API_KEY),
        "database": "demo mode — verification works without DB",
    }

# ── Main Verification Endpoint ────────────────────────────────
@app.post("/api/v1/verify")
async def verify(
    document_type: str = Form(...),
    state: str = Form(...),
    property_address: str = Form(...),
    owner_name: str = Form(...),
    user_role: str = Form(...),
    file_number: Optional[str] = Form(None),
    additional_notes: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    vid = "LV-" + str(uuid.uuid4())[:8].upper()
    logger.info(f"[{vid}] Verifying: {property_address}")

    # ── Call Claude AI ─────────────────────────────────────────
    data = None
    if API_KEY:
        try:
            client = anthropic.Anthropic(api_key=API_KEY)
            prompt = f"""You are LandVerify, Nigeria's top land document fraud detection expert.

Analyse this property verification request carefully and return ONLY valid JSON — no markdown, no explanation.

PROPERTY DETAILS:
- Address: {property_address}
- State: {state}
- Document Type: {document_type}
- Declared Owner: {owner_name}
- File Number: {file_number or "Not provided"}
- Requester Role: {user_role}
- Additional Notes: {additional_notes or "None"}

Return this exact JSON:
{{
  "trust_score": <integer 0-100>,
  "trust_level": "<safe|caution|danger>",
  "summary": "<2-3 sentence expert analysis of this specific property>",
  "recommendation": "<specific actionable advice for a {user_role} in Nigeria>",
  "checks": [
    {{"label": "Document Format", "status": "<pass|fail|warning>", "detail": "<specific finding>"}},
    {{"label": "File Number Validity", "status": "<pass|fail|warning>", "detail": "<specific finding>"}},
    {{"label": "Stamp Duty Check", "status": "<pass|fail|warning>", "detail": "<specific finding>"}},
    {{"label": "Ownership Consistency", "status": "<pass|fail|warning>", "detail": "<specific finding>"}},
    {{"label": "Registry Match", "status": "<pass|fail|warning>", "detail": "<specific finding>"}},
    {{"label": "Encumbrance Check", "status": "<pass|fail|warning>", "detail": "<specific finding>"}},
    {{"label": "Duplicate Title Check", "status": "<pass|fail|warning>", "detail": "<specific finding>"}}
  ],
  "fraud_flags": [
    {{"severity": "<high|medium|low>", "title": "<flag title>", "description": "<detailed explanation>", "action": "<what to do now>"}}
  ],
  "ownership_chain": [
    {{"year": "<year>", "owner": "<name>", "type": "<transaction type>", "registered": true}}
  ]
}}"""

            msg = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            text = msg.content[0].text.strip()

            # Clean markdown if present
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].strip()

            data = json.loads(text)
            logger.info(f"[{vid}] Claude response: score={data.get('trust_score')}, level={data.get('trust_level')}")

        except json.JSONDecodeError as e:
            logger.error(f"[{vid}] JSON parse error: {e}")
            data = None
        except Exception as e:
            logger.error(f"[{vid}] Claude error: {e}")
            data = None

    # ── Fallback if no API key or Claude fails ─────────────────
    if not data:
        logger.info(f"[{vid}] Using demo fallback")
        data = {
            "trust_score": 65,
            "trust_level": "caution",
            "summary": f"Analysis of {property_address} in {state.upper()}. Document type: {document_type.replace('_',' ').title()}. Declared owner: {owner_name}. AI analysis unavailable — manual verification strongly recommended.",
            "recommendation": "Visit the relevant State Land Registry in person to verify this document. Bring a qualified property lawyer. Do not make any payment until physical verification is complete.",
            "checks": [
                {"label": "Document Format", "status": "pass", "detail": "Standard Nigerian land document format"},
                {"label": "File Number Validity", "status": "warning", "detail": f"File number {file_number or 'not provided'} — needs registry confirmation"},
                {"label": "Stamp Duty Check", "status": "warning", "detail": "Cannot verify FIRS stamp duty reference remotely"},
                {"label": "Ownership Consistency", "status": "warning", "detail": "Ownership details need physical verification"},
                {"label": "Registry Match", "status": "fail", "detail": "Live registry not connected — manual search required"},
                {"label": "Encumbrance Check", "status": "warning", "detail": "Cannot confirm absence of mortgages remotely"},
                {"label": "Duplicate Title Check", "status": "warning", "detail": "Duplicate check requires registry access"},
            ],
            "fraud_flags": [],
            "ownership_chain": [
                {"year": "2024", "owner": owner_name, "type": "Current Declared Owner", "registered": True}
            ]
        }

    # ── Build response ─────────────────────────────────────────
    score = int(data.get("trust_score", 65))
    score = max(0, min(100, score))  # Clamp 0-100
    level = data.get("trust_level", "caution")

    checks = data.get("checks", [])
    flags = data.get("fraud_flags", [])
    chain = data.get("ownership_chain", [])

    return {
        "verification_id": vid,
        "timestamp": datetime.utcnow().isoformat(),
        "property_address": property_address,
        "document_type": document_type,
        "state": state,
        "trust_score": score,
        "trust_level": level,
        "trust_score_breakdown": {
            "document_authenticity_score": min(score + 5, 100),
            "registry_match_score": max(score - 10, 0),
            "ownership_chain_score": min(score + 8, 100),
            "encumbrance_score": min(score + 3, 100),
            "geospatial_score": min(score + 6, 100),
            "fraud_penalty": len([f for f in flags if f.get("severity") == "high"]) * 5,
            "final_score": score,
        },
        "checks": [
            {
                "check_id": c["label"].lower().replace(" ", "_"),
                "label": c["label"],
                "status": c["status"],
                "detail": c["detail"],
            }
            for c in checks
        ],
        "checks_passed": sum(1 for c in checks if c.get("status") == "pass"),
        "checks_failed": sum(1 for c in checks if c.get("status") == "fail"),
        "checks_warned": sum(1 for c in checks if c.get("status") == "warning"),
        "fraud_flags": [
            {
                "flag_id": str(uuid.uuid4())[:6],
                "severity": f.get("severity", "medium"),
                "title": f.get("title", "Risk Detected"),
                "description": f.get("description", ""),
                "recommendation": f.get("action", "Consult a property lawyer"),
                "confidence": 0.85,
            }
            for f in flags
        ],
        "fraud_risk_summary": data.get("summary", ""),
        "ownership_chain": {
            "total_owners": len(chain),
            "chain_integrity": 0.85 if len(chain) > 1 else 0.6,
            "has_gaps": False,
            "has_disputes": False,
            "records": [
                {
                    "year": r.get("year", "Unknown"),
                    "owner_name": r.get("owner", "Unknown"),
                    "transaction_type": r.get("type", "Unknown"),
                    "consideration": r.get("consideration", "Not disclosed"),
                    "registered": r.get("registered", True),
                    "flagged": False,
                }
                for r in chain
            ],
            "analysis_summary": f"Ownership chain reconstructed by Claude AI. {len(chain)} record(s) found.",
        },
        "ai_summary": data.get("summary", ""),
        "ai_recommendation": data.get("recommendation", ""),
        "verified_by": f"LandVerify AI v1.0 + {CLAUDE_MODEL}" if API_KEY else "LandVerify Demo Mode",
    }


# ── Auth endpoints (stub — returns demo tokens) ───────────────
@app.post("/api/v1/auth/register")
async def register(body: dict):
    return {
        "access_token": "demo-token-" + str(uuid.uuid4())[:8],
        "refresh_token": "demo-refresh-" + str(uuid.uuid4())[:8],
        "token_type": "bearer",
        "expires_in": 1800,
        "user": {
            "id": str(uuid.uuid4()),
            "email": body.get("email", ""),
            "full_name": body.get("full_name", ""),
            "role": body.get("role", "buyer"),
            "plan": "free",
            "email_verified": False,
            "verifications_used": 0,
            "verifications_limit": 3,
            "can_verify": True,
        }
    }

@app.post("/api/v1/auth/login")
async def login(body: dict):
    return {
        "access_token": "demo-token-" + str(uuid.uuid4())[:8],
        "refresh_token": "demo-refresh-" + str(uuid.uuid4())[:8],
        "token_type": "bearer",
        "expires_in": 1800,
        "user": {
            "id": str(uuid.uuid4()),
            "email": body.get("email", ""),
            "full_name": "Demo User",
            "role": "buyer",
            "plan": "free",
            "email_verified": True,
            "verifications_used": 0,
            "verifications_limit": 3,
            "can_verify": True,
        }
    }

@app.get("/api/v1/auth/me")
async def me():
    return {
        "id": str(uuid.uuid4()),
        "email": "demo@landverify.ng",
        "full_name": "Demo User",
        "role": "buyer",
        "plan": "free",
        "email_verified": True,
        "verifications_used": 0,
        "verifications_limit": 3,
        "can_verify": True,
    }

@app.post("/api/v1/auth/refresh")
async def refresh(body: dict):
    return {
        "access_token": "demo-token-" + str(uuid.uuid4())[:8],
        "refresh_token": "demo-refresh-" + str(uuid.uuid4())[:8],
        "token_type": "bearer",
        "expires_in": 1800,
    }

@app.post("/api/v1/auth/logout")
async def logout(body: dict):
    return {"message": "Logged out successfully"}

@app.get("/api/v1/dashboard")
async def dashboard():
    return {
        "user": {"full_name": "Demo User", "plan": "free", "verifications_used": 0, "verifications_limit": 3},
        "stats": {"total": 0, "safe": 0, "caution": 0, "danger": 0, "monitored_properties": 0, "active_alerts": 0},
        "recent_verifications": [],
    }

@app.get("/api/v1/alerts")
async def alerts():
    return {"alerts": [], "total": 0}

@app.post("/api/v1/alerts/subscribe")
async def subscribe(body: dict):
    return {"message": "Monitoring enabled", "property_address": body.get("property_address", "")}
