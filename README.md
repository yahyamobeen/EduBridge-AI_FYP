# EduBridge AI

A **secure, agentic, multilingual learning platform** for Pakistani students (Classes 9–12), curriculum-grounded to the Punjab (PCTB) and Sindh (STBB) boards.

> Final Year Project — BS Data Science (2023–2027)
> Faculty of Computing & Information Technology (FCIT), University of the Punjab, Lahore

---

## Overview

EduBridge AI lets a student ask curriculum questions in **English, Urdu, or Roman-Urdu** (typed or spoken) and receive grounded, class-adaptive answers with retrieval-first visual aids and a talking avatar tutor. On top of the tutor sits a classroom layer for teachers and parents, an adaptive assessment engine, and a cross-cutting **Secure Skills & MCP Layer** that vets every agent skill and MCP server against OWASP guidance.

**Key capabilities**

- Curriculum-exact tutoring grounded in official PCTB / STBB textbooks (Classes 9–12)
- Multilingual: answers *generated* in the student's language (not post-translated)
- Retrieval-first visual aids + avatar tutor with Urdu/English speech
- Per-SLO mastery (BKT), IRT-calibrated difficulty, and a single exam-readiness score
- Classroom spaces with secure, auto-graded quizzes and weak-area analytics
- Secure by design: skill/MCP vetting, least-privilege manifests, sandboxing, AgentSBOM

## Documentation

| Document | Description |
|---|---|
| [`prd.md`](prd.md) | **Product Requirements** — personas, RBAC, functional & non-functional requirements, security, KPIs |
| [`tdd.md`](tdd.md) | **Technical Design** — architecture, data model (OLTP + vector + OLAP), APIs, security layer |

> These two documents are the source of truth for the build. `prd.md` drives `tdd.md`, which drives Epics → Stories → Tasks.

## Architecture

| Layer | Technology |
|---|---|
| Frontend | Next.js · React · Tailwind (responsive web, EN/UR/Roman-Urdu, RTL) |
| Backend | FastAPI modular monolith (Python 3.12+) |
| Agent | Qwen + LangGraph, skills exposed over MCP |
| Data | PostgreSQL (OLTP) · vector DB (embeddings) · star-schema OLAP · Redis |
| Models | Qwen · Whisper · BGE-M3 + reranker · Fish Audio S2 Pro · MuseTalk · Llama Guard 3 |
| Security | Secure Skills & MCP Layer — vetting, least-privilege manifests, sandboxing, AgentSBOM |

## Repository structure

```
backend/         FastAPI modular monolith (auth, agent, retrieval, assessment, classroom, security, analytics, workers)
frontend/        Next.js application
mcp-servers/     Audited MCP servers (tts_avatar, stt, ocr, translation, web_search)
ml/              Model serving configs and evaluation harness
infra/           Docker and deployment configuration
.github/         CI/CD workflows
```

## Getting started

> Implementation has not started yet — the scaffold reflects the structure defined in [`tdd.md`](tdd.md) §8.3. Setup instructions will be added with the first backend and frontend commits.

## Team

| Member | Registration |
|---|---|
| Yahya Mobeen *(Group Leader)* | BSDSF23A039 |
| Osairum Ahmad Khan | BSDSF23A019 |
| Muhammad Mujtaba | BSDSF23A026 |
| Abdul Muneeb | BSDSF23A036 |

**Supervisor:** Dr. Muhammad Arif Butt — Department of Data Science, FCIT

## Contributing workflow

`main` is protected and always holds stable, releasable code — never commit to it directly.

1. Branch from an up-to-date `main`: `feature/<epic>-<short-description>`
2. Commit your work and push the branch
3. Open a Pull Request — it links the story and must pass CI
4. The team lead reviews and merges
5. Delete the feature branch after merge

```bash
git checkout main && git pull && git checkout -b feature/auth-jwt-login
```

## License

Academic project — all rights reserved. Curriculum content is used for educational purposes with attribution.
