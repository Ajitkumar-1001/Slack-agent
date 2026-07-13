import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_SIGNING_SECRET", "test-signing-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("GITHUB_TOKEN", "ghp-test")
os.environ.setdefault("GITHUB_OWNER", "test-owner")
os.environ.setdefault("GITHUB_REPO", "test-repo")


@pytest.fixture
def valid_plan_dict() -> dict:
    """A complete, valid ProjectPlan payload (raw dict — no schema import) shared by
    the schema and Block Kit tests. Four risks (one 'low') so 'top 3 risks' is a real subset."""
    return {
        "project_name": "Onboarding Redesign",
        "objective": "Ship a redesigned onboarding flow in four weeks",
        "timeline": "4 weeks",
        "milestones": [
            {
                "title": "Design",
                "description": "Approved wireframes and mocks",
                "due_date": None,
                "success_criteria": ["approved mocks"],
            }
        ],
        "tasks": [
            {
                "title": "Build wireframes",
                "description": "Three onboarding screens",
                "milestone": "Design",
                "suggested_owner": None,
                "priority": "high",
                "acceptance_criteria": ["3 screens reviewed"],
                "dependencies": [],
            }
        ],
        "risks": [
            {"title": "No owner", "severity": "high", "explanation": "Unassigned", "mitigation": "Assign a PM"},
            {"title": "Tight timeline", "severity": "medium", "explanation": "Four weeks", "mitigation": "Cut scope"},
            {"title": "Dep on Auth API", "severity": "critical", "explanation": "External", "mitigation": "Stub it"},
            {"title": "Unclear scope", "severity": "low", "explanation": "Fuzzy", "mitigation": "Clarify with stakeholders"},
        ],
        "dependencies": [
            {"title": "Auth API", "description": "External auth service", "type": "external", "blocking": True}
        ],
        "assumptions": ["A design system already exists"],
        "evidence_summary": ["Thread references a Q3 launch commitment"],
    }


@pytest_asyncio.fixture
async def db_session():
    """An in-memory SQLite AsyncSession with the schema created from the models.
    Lets state-transition / persistence tests exercise real DB behavior offline."""
    import db.models  # noqa: F401  (register all tables on Base.metadata)
    from db.session import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()
