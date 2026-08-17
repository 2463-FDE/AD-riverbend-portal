"""
Demo entry for the w4 knowledge-graph patient-view prototype.

    python eval/kg/run.py

Assembles the 53-encounter fixture chart for the caller bound to it, prints
the view summary and the retrieval count, then walks the caller to the sibling
id — the same walk docs/handover/portal.har captured against the production
route — and prints the refusal.

Nothing here touches a database, a service, or a real chart: the corpus is the
synthetic in-memory sample in eval/kg/corpus.py (w4-D-1).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import assemble  # noqa: E402
import corpus  # noqa: E402


def main():
    store = assemble.GraphStore(corpus.build_corpus())
    own = corpus.FIXTURE_PATIENT_ID
    sibling = corpus.SIBLING_PATIENT_ID
    principal = assemble.Principal.for_patient(own)

    view = assemble.assemble_patient_view(store, principal, own)
    records = sum(len(a.records) for a in view.encounters)
    print(f"caller {principal.subject} -> patient {view.patient_id}")
    print(
        f"  assembled: {len(view.encounters)} encounters, "
        f"{len(view.visit_summaries())} visit summaries, "
        f"{len(view.labs())} labs, {records} records total"
    )
    print(f"  retrievals: {store.retrievals}")
    print(f"  first summary: {view.encounters[0].encounter.summary}")

    store.reset_retrievals()
    try:
        assemble.assemble_patient_view(store, principal, sibling)
    except assemble.NotAuthorized as refusal:
        print(f"caller {principal.subject} -> patient {sibling}")
        print(f"  refused at the graph boundary: {refusal}")
        print(f"  retrievals: {store.retrievals}")
    else:  # pragma: no cover - the boundary tests pin this branch as dead
        raise SystemExit("boundary did not refuse the cross-patient request")


if __name__ == "__main__":
    main()
