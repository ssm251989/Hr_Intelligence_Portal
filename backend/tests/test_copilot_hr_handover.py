"""Part 23.3d: "Hand over to HR" (Helpdesk off) always failed with "Something went wrong" - the HR to-do was saved
with agent="copilot", which the CHECK agent_suggestions_agent_check refuses. The to-do is now saved (as helpdesk
triage) and shows in My approvals."""
from app.copilot.service import CopilotService
from app.models.intelligence import AGENTS, AgentSuggestion

from tests.test_intelligence import TENANT, _user


def test_hand_to_hr_saves_the_todo(db_session):
    user = _user(db_session, permissions=["copilot.chat.view"])
    user.full_name = "Asha Asker"
    svc = CopilotService(db_session, TENANT, user)
    svc._hand_to_hr({"subject": "Pets at the office?", "description": "Is there a company policy on bringing pets to the office?"})
    db_session.flush()
    todo = db_session.query(AgentSuggestion).filter(AgentSuggestion.kind == "copilot_question",
                                                    AgentSuggestion.title.like("Question from Asha Asker:%")).one()
    assert todo.agent in AGENTS
    assert todo.status == "pending" and todo.payload_json["question"].startswith("Is there a company policy")
