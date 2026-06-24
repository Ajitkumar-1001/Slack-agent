# FlowPilot AI

### Autonomous Project Execution Agent for Slack

> From idea to execution — directly inside Slack.

FlowPilot AI is a Slack-native multi-agent system that transforms high-level business goals into actionable execution plans, continuously coordinates work, retrieves organizational knowledge, tracks project progress, and generates stakeholder updates—all without leaving Slack.

Built for the Slack Agent Builder Challenge 2026.

---

# Problem

Organizations spend significant time coordinating work rather than executing it.

A simple request such as:

> "Launch the new customer onboarding experience next month."

typically requires:

* Project planning
* Task breakdown
* Documentation creation
* Knowledge discovery
* Stakeholder alignment
* Progress tracking
* Status reporting

Today this information is fragmented across:

* Slack
* Jira
* GitHub
* Notion
* Google Drive
* Internal documentation systems

As projects grow, context becomes scattered, execution slows, and teams spend more time searching for information than delivering outcomes.

---

# Solution

FlowPilot AI acts as an autonomous project execution layer inside Slack.

Instead of simply answering questions, FlowPilot:

* Converts goals into execution plans
* Creates milestones and tasks
* Retrieves relevant organizational knowledge
* Identifies risks and blockers
* Tracks project progress
* Generates stakeholder reports
* Coordinates actions across connected systems

All through a natural Slack conversation.

---

# Key Features

## Project Planning Agent

Convert high-level objectives into:

* Milestones
* Deliverables
* Timelines
* Workstreams

Example:

User:

```text
Launch our onboarding redesign in four weeks.
```

FlowPilot:

```text
✓ Generated project roadmap
✓ Created milestones
✓ Identified dependencies
✓ Assigned workstreams
```

---

## Knowledge Agent

Searches:

* Slack conversations
* Project channels
* Documentation
* Connected knowledge bases

Uses Retrieval-Augmented Generation (RAG) to provide grounded responses.

---

## Multi-Agent Orchestration

FlowPilot uses specialized agents coordinated by a supervisor.

Agents include:

* Planning Agent
* Knowledge Agent
* Risk Agent
* Reporting Agent
* Action Agent

Each agent has a focused responsibility while collaborating toward a shared objective.

---

## Risk Detection

Continuously identifies:

* Delayed milestones
* Missing dependencies
* Resource conflicts
* Unanswered blockers

and proactively alerts teams.

---

## Automated Reporting

Generate:

* Daily updates
* Weekly reports
* Executive summaries
* Project health assessments

directly within Slack.

---

## MCP Integrations

FlowPilot connects external systems through MCP.

Examples:

* GitHub
* Jira
* Notion
* Google Drive
* Internal tools

The Action Agent can create tasks, update documents, and synchronize project state across platforms.

---

# Architecture

```text
┌─────────────────────┐
│      Slack UI       │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Supervisor Agent   │
└──────────┬──────────┘
           │
 ┌─────────┼─────────┐
 │         │         │
 ▼         ▼         ▼

Planning  Knowledge  Risk
 Agent     Agent    Agent

           │
           ▼

    Retrieval Layer
      (RAG + RTS)

           │
           ▼

      MCP Layer

 GitHub • Jira • Notion
 Google Drive • Internal APIs
```

---

# Technology Stack

## Slack

* Slack Agent Builder
* Slack Events API
* Slack Bolt SDK
* Slack Real-Time Search API

## AI Layer

* LangGraph
* OpenAI / Anthropic Models
* Multi-Agent Architecture
* RAG

## Backend

* FastAPI
* Python
* PostgreSQL
* Supabase

## Retrieval

* pgvector
* Semantic Search
* Hybrid Search
* Knowledge Indexing

## Infrastructure

* Docker
* GitHub Actions
* CI/CD
* Cloud Deployment

---

# Example Workflow

## User Request

```text
Launch a customer onboarding redesign in four weeks.
```

## Planning Agent

Creates:

* Goals
* Milestones
* Deliverables

## Knowledge Agent

Finds:

* Previous onboarding projects
* Existing documentation
* Historical discussions

## Risk Agent

Identifies:

* Missing requirements
* Resource constraints
* Timeline risks

## Action Agent

Creates:

* Jira epics
* GitHub issues
* Documentation pages

## Reporting Agent

Posts:

```text
Weekly Project Summary

Progress: 72%
Open Risks: 3
Blocked Tasks: 1
Expected Completion: On Track
```

---

# Why FlowPilot?

Most AI assistants stop at information retrieval.

FlowPilot goes further by helping teams execute work.

| Traditional AI Assistant | FlowPilot AI           |
| ------------------------ | ---------------------- |
| Answers questions        | Drives execution       |
| Reactive                 | Proactive              |
| Single interaction       | Long-running workflows |
| Search focused           | Outcome focused        |
| Single agent             | Multi-agent system     |

---

# Impact

FlowPilot helps organizations:

* Reduce project planning overhead
* Eliminate context switching
* Surface organizational knowledge
* Improve project visibility
* Detect blockers earlier
* Accelerate execution

---

# Future Roadmap

### v2

* Multi-project portfolio management
* Cross-workspace intelligence
* Predictive project risk forecasting
* Resource planning recommendations
* Executive dashboards

### v3

* Autonomous task ownership
* Self-healing project workflows
* AI-powered organizational memory

---

# Team

### AI Architecture Lead

Designs multi-agent orchestration, reasoning workflows, retrieval systems, and MCP integrations.

### Product & Platform Lead

Builds Slack experiences, backend services, deployment pipelines, integrations, and production infrastructure.

---

# Built for

Slack Agent Builder Challenge 2026

Leveraging:

* Slack Agents
* MCP Integrations
* Real-Time Search API

to create the next generation of AI-powered workplace execution.

---

# Backend Setup (FastAPI MVP)

This repo includes a production-ready hackathon MVP backend for the Slack app, REST API, and Supabase persistence.

## Project structure

```text
app/
├── main.py                 # FastAPI entry point
├── config.py               # Environment settings
├── api/projects.py         # REST endpoints
├── slack/
│   ├── handlers.py         # /slack/commands, events, interactions
│   ├── blocks.py           # Block Kit builders
│   ├── client.py           # Slack Web API helpers
│   └── verify.py           # Request signature verification
├── agents/orchestrator.py  # generate_project_plan() integration contract
├── db/repository.py        # Supabase + in-memory fallback
├── models/schemas.py       # Pydantic models
└── services/project_service.py
database/schema.sql         # PostgreSQL schema for Supabase
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/slack/commands` | Slash command `/flowpilot` |
| `POST` | `/slack/events` | Slack Events API |
| `POST` | `/slack/interactions` | Block Kit button actions |
| `POST` | `/api/projects` | Create project from goal |
| `GET` | `/api/projects/{id}` | Get project with relations |
| `GET` | `/api/projects/{id}/tasks` | List tasks |
| `GET` | `/api/projects/{id}/risks` | List risks |
| `GET` | `/api/projects/{id}/summary` | Project status summary |

## Local development

### 1. Prerequisites

- Python 3.11+
- [Supabase](https://supabase.com) project (optional for local demo — in-memory fallback works)
- [Slack app](https://api.slack.com/apps) with Bot Token + Signing Secret

### 2. Install

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

### 3. Configure `.env`

Set at minimum for a local API demo:

```bash
AGENT_USE_MOCK=true
```

For full Slack + database integration:

```bash
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=your-service-role-key
```

### 4. Database

Run `database/schema.sql` in the Supabase SQL Editor.

### 5. Run the server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

### 6. Test without Slack

```bash
curl -X POST http://localhost:8000/api/projects \
  -H "Content-Type: application/json" \
  -d '{"goal": "Launch customer onboarding redesign in 4 weeks"}'
```

## Slack app configuration

1. Create a Slack app at https://api.slack.com/apps
2. **Slash Commands** → create `/flowpilot` → Request URL: `https://<your-host>/slack/commands`
3. **Event Subscriptions** → Enable → Request URL: `https://<your-host>/slack/events`
4. **Interactivity** → Enable → Request URL: `https://<your-host>/slack/interactions`
5. **OAuth & Permissions** → add scopes: `chat:write`, `commands`
6. Install app to workspace and copy Bot Token + Signing Secret to `.env`

### Local Slack testing with ngrok

```bash
ngrok http 8000
```

Use the ngrok HTTPS URL as the Request URL base for all three Slack endpoints.

### Slash command flow

```text
User: /flowpilot Launch customer onboarding redesign in 4 weeks
  → Immediate loading Block Kit response
  → Background: generate_project_plan() → save to DB
  → Delayed response_url update with full plan + action buttons
```

## AI agent integration

The AI team implements planning logic in `app/agents/orchestrator.py`:

```python
from app.agents.orchestrator import generate_project_plan

plan = generate_project_plan("Launch onboarding redesign in 4 weeks")
```

Set `AGENT_USE_MOCK=false` and `OPENAI_API_KEY=...` to use the optional OpenAI path, or replace `generate_project_plan` with your LangGraph orchestrator.

## Deployment notes

### Railway / Render / Fly.io

1. Set environment variables from `.env.example`
2. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Point Slack Request URLs to your deployed HTTPS domain

### Docker

```bash
docker build -t flowpilot-api .
docker run -p 8000:8000 --env-file .env flowpilot-api
```

### Production checklist

- [ ] `SLACK_SIGNING_SECRET` set (verification enforced outside `development`)
- [ ] Supabase schema applied
- [ ] `AGENT_USE_MOCK=false` with real agent wired in
- [ ] HTTPS termination in front of FastAPI
- [ ] Log aggregation (stdout → CloudWatch/Datadog/etc.)
