"""
agent_turn — the agent path: model₁ → retriever → [payer] → model₂, inside the
framework's run (eligibility-assistant SPEC-21).

The module holds the turn's bounded state, the middleware that runs the payer call
and injects the status, the once-guard that keeps the payer call at most one per
turn (SPEC-51), and ``run_agent_path``.

``llm_client`` and ``eligibility_client`` are imported as MODULES, never
``from … import check_coverage``: both are resolved as attributes at call time so a
test rig patching the module attribute is what the turn actually calls
(eligibility-assistant-D-66 note 2).
"""
import eligibility_client
import llm_client
