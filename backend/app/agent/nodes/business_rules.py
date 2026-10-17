from app.agent.nodes._identity import require_customer_id
from app.agent.state import AgentState
from app.schemas.agent import Intent
from app.tools.upsell import check_upgrade_eligibility


def business_rules_node(state: AgentState) -> dict:
    if state["intent"] == Intent.UPGRADE_REQUEST:
        eligibility = check_upgrade_eligibility(require_customer_id(state))
        return {"eligibility_result": eligibility}

    return {}
