# LalFita Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER / CITIZEN                                 │
│                  (Small business owner in India)                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        LALFITA PORTAL (Frontend)                           │
│                 FastAPI + HTML (or future React app)                       │
│                    http://localhost:8080                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     AGENTS SERVICE (Cloud Run)                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                     SENTINEL (Orchestrator)                         │  │
│  │   - Receives journey creation requests                              │  │
│  │   - Coordinates multi-agent workflows                               │  │
│  │   - Manages state transitions                                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│         ┌─────────────────────────┼─────────────────────────┐             │
│         ▼                         ▼                         ▼             │
│  ┌─────────────┐          ┌─────────────┐          ┌─────────────┐       │
│  │  PATHFINDER │          │    CLERK    │          │   LIAISON   │       │
│  │   (ADK)     │          │   (ADK)     │          │   (ADK)     │       │
│  │             │          │             │          │             │       │
│  │ Researches  │          │ Parses &    │          │ Handles     │       │
│  │ which       │          │ validates   │          │ government  │       │
│  │ licenses    │          │ documents   │          │ notices &   │       │
│  │ apply       │          │             │          │ responses   │       │
│  └─────────────┘          └─────────────┘          └─────────────┘       │
│         │                         │                         │             │
│         └─────────────────────────┼─────────────────────────┘             │
│                                   ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │              VERTEX AI (gemini-3.5-flash)                           │  │
│  │    - LLM inference for all agents                                   │  │
│  │    - Search grounding for Pathfinder research                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    GCP EVENT INFRASTRUCTURE                                │
│                                                                           │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐   │
│  │   Pub/Sub        │    │   Firestore      │    │   Cloud Storage  │   │
│  │   (lalfita-      │    │   ( journeys,    │    │   (document      │   │
│  │    events)       │    │    requirements) │    │    vault )       │   │
│  └──────────────────┘    └──────────────────┘    └──────────────────┘   │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    GOVERNMENT SANDBOX (Mock)                               │
│           (Simulated GST, FSSAI, Udyam APIs for testing)                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Agent Flow

1. **User** submits goal (e.g., "Start home food business in Ahmedabad")
2. **Sentinel** creates journey, publishes `journey.created` event
3. **Pathfinder** researches applicable licenses → updates journey
4. **Clerk** parses user documents, validates completeness
5. **Liaison** submits applications, handles rejections/notices
6. **Events** flow through Pub/Sub for async resilience
7. **State** persisted in Firestore for multi-day bureaucratic waits

## Technology Stack

| Component | Technology |
|-----------|------------|
| Runtime | Python 3.13 |
| LLM | Google Vertex AI (gemini-3.5-flash) |
| Agent Framework | Google ADK 2.7.0 |
| Orchestration | Event-driven (Pub/Sub) |
| Database | Cloud Firestore |
| Storage | Cloud Storage |
| Compute | Cloud Run (serverless) |
| API Gateway | FastAPI + Uvicorn |

## Key Design Decisions

- **Event-driven**: Long-running bureaucratic processes can't use request/response. Pub/Sub decouples agents.
- **Fixture fallback**: If Vertex fails, system degrades to canned fixtures so demos never break.
- **SIM_DAY_SECONDS**: Compresses 3-week waits into seconds for demo pacing.