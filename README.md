# JobOS backend

FastAPI service behind [JobOS](https://job-os-frontend-puce.vercel.app), an AI job-search toolkit. It parses resumes, builds prompts, calls the Groq LLM API, and returns structured JSON to the React frontend.

**Live demo:** https://job-os-frontend-puce.vercel.app
**Frontend repo:** https://github.com/prans8/JobOS-frontend

> Hosted on a free tier that sleeps when idle. The first request after a break can take 30-60 seconds.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/analyze-resume` | Multipart upload (`resume` file + `job_description`). Returns match score, strengths, missing keywords, improvements and a summary. |
| `POST` | `/interview/start` | Takes company, role and round type. Returns an interviewer intro and 5 AI-generated questions. |
| `POST` | `/interview/evaluate` | Scores one spoken answer (and optional code) and returns feedback plus the interviewer's reply. |
| `POST` | `/interview/final-report` | Takes all answers and scores. Returns an overall score, recommendation and tips. |
| `POST` | `/referral/messages` | Drafts a connection note, follow-up and referral ask from facts the user provides. |
| `GET` | `/` | Health check. |

## Stack

Python 3.12, FastAPI, Uvicorn, Pydantic, PyMuPDF (PDF), python-docx (Word), Groq SDK.

## Run locally

```bash
python -m venv venv
venv\Scripts\activate            # Windows  (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
# create a .env file containing: GROQ_API_KEY=your_key
python -m uvicorn main:app --reload
```

Interactive API docs are served at `http://127.0.0.1:8000/docs`.

## Environment variables

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | Required. Groq API key. Never commit it. |
| `GROQ_MODEL` | Optional. Overrides the default model (`openai/gpt-oss-120b`). |
| `FRONTEND_ORIGINS` | Deployed frontend address(es), comma separated, allowed by CORS. |

## Deploy (Render)

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Environment: `GROQ_API_KEY`, `FRONTEND_ORIGINS`, `PYTHON_VERSION=3.12.6`

## Design notes

- Stateless: no database, and uploaded resumes are processed in memory and not saved. The extracted text is sent to the Groq API.
- Model replies are parsed with a tolerant JSON extractor, because models sometimes wrap JSON in text or code fences.
- The model name lives in one place so a retired model is a one-line change. Groq retired the original model this project used.
- Interview questions are AI-generated for the company and role. They are not taken from real interview reports.

## Possible next steps

Rate limiting and request-size limits, automated tests, and persistence for saved results.