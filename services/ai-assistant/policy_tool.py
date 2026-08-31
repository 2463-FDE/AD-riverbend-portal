"""
policy_tool — the one model-facing retriever tool (eligibility-assistant SPEC-9).

`make_policy_lookup(payer, product, state)` returns a LangChain `StructuredTool` whose
single argument is `topic`, a `Literal` over the manifest's category values. Payer,
product and state are bound by the APPLICATION from the turn's clerk selections at
construction and are never taken from the model: there is no free-text argument, no
document-id argument, and no key the model can add.

The schema is explicit — `PolicyLookupArgs` with `extra="forbid"` — and passed as
`args_schema`, not inferred from the function signature: in the pinned
`langchain-core==1.6.0` the inferred subset model is rebuilt with
`ConfigDict(arbitrary_types_allowed=True)` only, so `extra="forbid"` does not survive and
an extra key would be silently dropped rather than rejected. With the explicit schema all
three SPEC-9 clauses hold by one mechanism: an extra argument, a free-text value and a
document id each raise `ValidationError` before `policy_index.lookup` is reached.

The `Literal` is built at import from `policy_index.categories()`, which runs the
sha-verifying `load()` — so importing this module (and therefore `app`) reads and verifies
the corpus, never a hand list.
"""
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

import policy_index

TOPICS = policy_index.categories()


class PolicyLookupArgs(BaseModel):
    """The model's whole argument surface: one closed-enum topic."""

    model_config = ConfigDict(extra="forbid")

    topic: Literal[*TOPICS] = Field(  # type: ignore[valid-type]
        description="The policy topic to retrieve approved documents for."
    )


# The tool's own provenance (eligibility-assistant-SPEC-63): the model chooses the topic,
# the application binds the other three from the clerk's selections. The record the
# lookup leaves is never returned to the model — only the rows are.
_PROVENANCE = {
    "topic": "model_topic",
    "payer": "clerk_selection",
    "product": "clerk_selection",
    "state": "clerk_selection",
}


def make_policy_lookup(payer: str, product: str, state: str) -> StructuredTool:
    """Bind the turn's clerk selections and return the one-argument `policy_lookup` tool."""
    policy_index._check_enum(payer, policy_index.PAYERS, "payer")
    policy_index._check_enum(product, policy_index.PRODUCTS, "product")
    policy_index._check_enum(state, policy_index.STATES, "state")

    def policy_lookup(topic: str) -> list:
        """Look up approved policy documents for a topic."""
        rows, _record = policy_index.lookup(
            topic, payer, product, state, provenance=_PROVENANCE
        )
        return [row.as_dict() for row in rows]

    return StructuredTool.from_function(
        func=policy_lookup,
        name="policy_lookup",
        description=(
            "Retrieve the approved policy documents for one topic. The payer, product and "
            "state are already set from the clerk's selections."
        ),
        args_schema=PolicyLookupArgs,
        infer_schema=False,
    )
