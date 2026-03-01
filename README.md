# LandVerify — Nigeria's Land Trust Layer

AI-powered land document verification. Works on Railway, Render, Replit, and Google Colab.

---

## Quick Deploy

### Railway
1. Connect this repo to Railway
2. Add environment variable: `ANTHROPIC_API_KEY` = your key
3. Deploy — Railway auto-detects `railway.json`

### Render
1. Connect this repo to Render
2. Build Command: `pip install -r requirements.txt`
3. Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add environment variable: `ANTHROPIC_API_KEY` = your key

### Replit
1. Import this repo into Replit
2. Add Secret: `ANTHROPIC_API_KEY` = your key
3. Tap Run — `.replit` file handles everything

### Google Colab
```python
import os, subprocess, threading, time
os.environ["ANTHROPIC_API_KEY"] = "your-key-here"
!pip install -r requirements.txt -q
def run(): subprocess.run(["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"])
threading.Thread(target=run, daemon=True).start()
time.sleep(5)
from google.colab.output import eval_js
print(eval_js("google.colab.kernel.proxyPort(8000)"))
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Health check |
| GET | `/health` | System status |
| POST | `/api/v1/verify` | Full AI verification |
| GET | `/docs` | Interactive API docs |

---

## Frontend
Open `landverify.html` in any browser and paste your deployment URL.

Get your Anthropic API key at: https://console.anthropic.com
