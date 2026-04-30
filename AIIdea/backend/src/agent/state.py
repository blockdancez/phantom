from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    collected_data: str
    trend_analysis: str
    market_insights: str
    tech_assessment: str
    generated_ideas: list[dict]
    final_idea: dict
