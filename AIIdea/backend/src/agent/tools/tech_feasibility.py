import structlog
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()

TECH_PROMPT = """You are a senior tech architect. Assess the technical feasibility of building:

Idea: {idea}
Requirements: {requirements}

Evaluate:
1. Core technology stack recommendation
2. Technical complexity (1-10)
3. Estimated development time (solo developer vs team)
4. Key technical risks and mitigations
5. Required APIs/services
6. Scalability considerations

Be realistic and specific."""


@tool
async def assess_tech_feasibility(idea: str, requirements: str = "") -> str:
    """Assess technical feasibility of a product idea including stack, complexity, timeline, and risks."""
    logger.info("工具_技术可行性", idea=idea[:80])

    llm = ChatOpenAI(model="gpt-4o", temperature=0.3)
    prompt = TECH_PROMPT.format(idea=idea, requirements=requirements)
    response = await llm.ainvoke(prompt)
    return response.content
