from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import fitz
import docx
import os
import groq
import json
import io

load_dotenv()

app = FastAPI()

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print("VALIDATION ERROR:", exc.errors())
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

# Deployed frontend address(es), comma separated, e.g.
# FRONTEND_ORIGINS=https://jobos.vercel.app
EXTRA_ORIGINS = [o.strip().rstrip("/") for o in os.getenv("FRONTEND_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        *EXTRA_ORIGINS,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = groq.Groq(api_key=os.getenv("GROQ_API_KEY"))

# Change the model in ONE place (or set GROQ_MODEL in backend/.env).
# llama-3.3-70b-versatile was shut down by Groq on 16 Aug 2026.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


def ask_llm_json(prompt: str, temperature: float) -> dict:
    """Send a prompt to Groq and return the reply parsed as JSON."""
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    content = (response.choices[0].message.content or "").strip()
    # Tolerate ```json fences or extra text around the JSON object
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Model did not return JSON: {content[:200]}")
    return json.loads(content[start:end + 1])

def extract_text(file_bytes: bytes, filename: str) -> str:
    if filename.endswith(".pdf"):
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    elif filename.endswith(".docx"):
        doc = docx.Document(io.BytesIO(file_bytes))
        return "\n".join(para.text for para in doc.paragraphs)
    else:
        return file_bytes.decode("utf-8", errors="ignore")

# ── Resume Analyzer ────────────────────────────────────────────────────────

@app.post("/analyze-resume")
async def analyze_resume(
    resume: UploadFile = File(...),
    job_description: str = Form(...)
):
    file_bytes = await resume.read()
    resume_text = extract_text(file_bytes, resume.filename)

    prompt = f"""
You are an expert ATS resume analyzer.

Analyze this resume against the job description below and return a JSON response with exactly these fields:
- match_score: number from 0-100
- missing_keywords: list of important keywords from the job description missing in the resume
- strengths: list of strong matching skills/experience
- improvements: list of specific suggestions to improve the resume
- summary: one paragraph summary of the overall fit

RESUME:
{resume_text}

JOB DESCRIPTION:
{job_description}

Return only valid JSON, nothing else.
"""

    result = ask_llm_json(prompt, 0.3)
    return result

# ── Mock Interview Coach ───────────────────────────────────────────────────

class InterviewStartRequest(BaseModel):
    company: str
    role: str
    round_type: str  # "HR" | "Technical" | "Behavioural"

class InterviewEvaluateRequest(BaseModel):
    company: str
    role: str
    round_type: str
    question: str
    answer: str
    question_number: int
    total_questions: int
    code: str = ""
    language: str = ""

@app.post("/interview/start")
async def interview_start(req: InterviewStartRequest):
    prompt = f"""
You are an expert interview coach who has studied thousands of real interview experiences shared on Glassdoor, Blind, LeetCode discuss, and Reddit for top companies.

Generate exactly 5 real interview questions that are genuinely asked at {req.company} for the role of {req.role} in a {req.round_type} round.

Rules:
- These must be REAL questions actually reported by candidates who interviewed at {req.company} for {req.role}
- Do NOT generate generic textbook questions
- For Technical rounds: focus on {req.company}'s known tech stack, system design patterns they care about, or coding problem types they favor
- For HR rounds: focus on {req.company}'s specific culture, values, and leadership principles
- For Behavioural rounds: focus on STAR-format situations relevant to {req.company}'s work culture
- Make questions sound like a real interviewer speaking, not a textbook
- Each question should be different in type and difficulty

Return ONLY valid JSON with this exact structure:
{{
  "interviewer_intro": "A 2-sentence intro from the interviewer introducing themselves and the round. Sound human and warm.",
  "questions": [
    "question 1",
    "question 2", 
    "question 3",
    "question 4",
    "question 5"
  ]
}}

Return only valid JSON, nothing else.
"""

    result = ask_llm_json(prompt, 0.7)
    return result


@app.post("/interview/evaluate")
async def interview_evaluate(req: InterviewEvaluateRequest):
    is_last = req.question_number == req.total_questions
    answer_text = req.answer.strip() or "(no spoken explanation given)"

    code_section = ""
    if req.code.strip():
        code_section = f'''
The candidate also wrote this {req.language or "code"} on the coding board:
-----
{req.code}
-----
Evaluate the code too: correctness, edge cases, time and space complexity, code quality, and whether the spoken explanation matches what the code actually does.
'''

    prompt = f"""
You are a senior interviewer at {req.company} evaluating a candidate for the role of {req.role} ({req.round_type} round).

Question asked: "{req.question}"

Candidate's spoken answer (transcribed from speech): "{answer_text}"
{code_section}

Evaluate the answer and return ONLY valid JSON with this exact structure:
{{
  "score": <number 1-10>,
  "verdict": "<one of: Excellent | Good | Average | Needs Improvement>",
  "what_went_well": "<1-2 sentences on what was strong about the answer>",
  "what_to_improve": "<1-2 sentences on what was weak or missing>",
  "ideal_answer_hint": "<2-3 sentences showing what a great answer would include, without giving it away completely>",
  "interviewer_response": "<A natural 1-2 sentence response from the interviewer, like a real human would say after hearing the answer. {'Thank them and say the interview is complete, give a warm closing.' if is_last else 'Acknowledge the answer briefly and transition naturally to the next question.'}>",
  "is_last": {str(is_last).lower()}
}}

Be honest but constructive. Sound like a real interviewer, not a robot.
Return only valid JSON, nothing else.
"""

    result = ask_llm_json(prompt, 0.4)
    return result


@app.post("/interview/final-report")
async def interview_final_report(data: dict):
    company = data.get("company")
    role = data.get("role")
    round_type = data.get("round_type")
    qa_pairs = data.get("qa_pairs", [])  # list of {question, answer, score, verdict}

    scores = [q["score"] for q in qa_pairs]
    avg_score = sum(scores) / len(scores) if scores else 0

    prompt = f"""
You are a senior hiring manager at {company} reviewing a mock {round_type} interview for the role of {role}.

Here are the candidate's answers and scores:
{json.dumps(qa_pairs, indent=2)}

Average score: {avg_score:.1f}/10

Generate a final interview report as valid JSON with this exact structure:
{{
  "overall_score": <number 1-10, the overall interview score>,
  "hiring_recommendation": "<one of: Strong Hire | Hire | Maybe | No Hire>",
  "overall_summary": "<3-4 sentences summarizing the overall interview performance>",
  "strongest_answer": "<which question number (1-5) had the best answer and why, in 1 sentence>",
  "weakest_area": "<what topic or skill needs the most work, in 1 sentence>",
  "top_3_tips": ["tip 1", "tip 2", "tip 3"],
  "encouragement": "<1 warm, genuine sentence of encouragement to the candidate>"
}}

Return only valid JSON, nothing else.
"""

    result = ask_llm_json(prompt, 0.4)
    result["avg_score"] = round(avg_score, 1)
    return result


# ── Referral Hunter ────────────────────────────────────────────────────────

class ReferralRequest(BaseModel):
    company: str
    role: str
    contact_type: str  # "recruiter" | "hiring_manager" | "alumni" | "peer"
    contact_name: str = ""
    contact_title: str = ""
    your_name: str = ""
    your_college: str = ""
    your_background: str = ""
    job_link: str = ""

CONTACT_GOALS = {
    "recruiter": "a recruiter / talent acquisition person at the company. Goal: find out if the role is open and how to get the resume seen. Direct and brief.",
    "hiring_manager": "a hiring or engineering manager at the company. Goal: show specific interest in the team and ask for a short chat or advice. Do NOT ask for a referral in the first message.",
    "alumni": "someone who studied at the same college as the candidate. Goal: use the shared college as common ground, ask for advice about the company, and only later ask for a referral.",
    "peer": "someone already working in the same role at the company. Goal: ask for advice about the role and team, build rapport first, ask for a referral only after they reply.",
}

@app.post("/referral/messages")
async def referral_messages(req: ReferralRequest):
    goal = CONTACT_GOALS.get(req.contact_type, CONTACT_GOALS["peer"])
    name = req.contact_name.strip() or "[Name]"
    first_name = req.contact_name.strip().split()[0] if req.contact_name.strip() else "[Name]"
    has_job_link = bool(req.job_link.strip())
    sender = req.your_name.strip() or "[Your Name]"
    background = req.your_background.strip() or "(none provided)"

    prompt = f"""
You write LinkedIn outreach messages for a job seeker who wants a referral.

Candidate name: {sender}
Candidate college: {req.your_college.strip() or "(not provided)"}
Candidate background (the ONLY facts you may use about them): {background}
Target company: {req.company}
Target role: {req.role}
Job link: {req.job_link.strip() or "(none)"}

The message recipient is {goal}
Recipient full name: {name}
Recipient title: {req.contact_title.strip() or "(not provided)"}

Write three messages and return ONLY valid JSON with exactly these fields:
- "connection_note": the note sent with the connection request. MAX 200 characters, count carefully. One specific reason for reaching out. No emojis.
- "follow_up_message": sent after they accept. 60-90 words. Ask ONE specific, easy-to-answer question about the role or team. No referral ask.
- "referral_ask": sent after they have replied or if the moment is right. 70-100 words. Polite, easy to decline, mentions the job link if one was given, offers to share the resume.
- "tip": one short sentence of practical advice for this specific type of contact.

Rules:
- Use only facts from the candidate background above. NEVER invent employers, projects, numbers, mutual connections, or claims of knowing the recipient.
- Do NOT state the candidate's degree status, graduation year, seniority, or years of experience (for example "recent graduate", "final-year student") unless the background says so.
- {"A job link was provided, so you may refer to that specific opening." if has_job_link else "NO job link was provided. Do NOT say you saw, noticed, or found a job opening, careers page, post, or news. Say only that you are interested in roles like the target role at the company."}
- Do NOT mention earlier conversations, earlier insights, or anything the recipient said before. The recipient has not told you anything yet. In the referral ask, you may only thank them for connecting or replying in general terms.
- Greet the recipient by FIRST NAME only, exactly as: "Hi {first_name},". Never use their first and last name together in the greeting.
- Sign off as "{sender}" exactly as written (keep the square brackets if present so the user can fill them in).
- Sound like a polite, real person. Avoid "I hope this message finds you well", "I am writing to", and flattery.

Return only valid JSON, nothing else.
"""
    result = ask_llm_json(prompt, 0.7)
    result["connection_note"] = str(result.get("connection_note", "")).strip()
    return result


@app.get("/")
def home():
    return {"message": "JobOS backend is running!"}