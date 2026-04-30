from src.agent.graph import create_agent_graph
from src.agent.state import AgentState


def test_agent_graph_compiles():
    graph = create_agent_graph()
    assert graph is not None


def test_agent_state_has_required_fields():
    state = AgentState(
        messages=[],
        collected_data="",
        trend_analysis="",
        market_insights="",
        tech_assessment="",
        generated_ideas=[],
        final_idea={},
    )
    assert "messages" in state
    assert "final_idea" in state
