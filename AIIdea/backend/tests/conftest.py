import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_idea_test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
# Tests stub out all LLM calls, so the real-key fast-fail in src.main would
# block pytest without adding any safety. Opt out explicitly.
os.environ.setdefault("AI_IDEA_FINDER_SKIP_KEY_CHECK", "1")
