# Front-desk eligibility procedure (synthetic training)

**Audience:** `['front_desk', 'admin']`  
**Product:** Riverbend Patient Portal eligibility assistant at check-in  
**Training-only:** not a historical Riverbend SOP dump

## Steps

1. Confirm the caller’s role. If not `front_desk` or `admin`, stop (unauthorized).
2. Confirm this request is for the current visit’s patient only. Cross-patient: refuse.
3. If this is an emergency presentation, start screening/stabilization. Eligibility continues in parallel and never gates emergency care.
4. Identify payer, product, state, and date of service.
5. Verify on a current official source. Cite title, ID, section, and date.
6. Classify: active, inactive, unknown, unavailable/pending, conflict, disputed.
7. Apply reverification triggers before reusing any prior result.
8. Separate eligibility from network, PCP/referral, prior authorization, cost-share, and COB order.
9. If any required fact is missing or sources conflict: cite both, refuse a definitive coverage answer, escalate.
10. Never state a payment guarantee.

## Done when

The clerk has a cited classification and next action (proceed / collect self-pay discussion / escalate / continue emergency care).
