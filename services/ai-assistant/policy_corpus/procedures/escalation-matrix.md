# Escalation matrix (synthetic training)

| Situation | Front desk does | Does not | Escalate to |
|---|---|---|---|
| Unauthorized role | Refuse assistant use | Give a coverage answer | Stop |
| Cross-patient request | Refuse | Look up another person | Privacy/supervisor |
| Conflict between sources | Cite both | Blend | Human/payer verification |
| Stale source only | Recheck or refuse | Use stale as current | Human/payer verification |
| Portal down | Unavailable script | Call it a denial | Supervisor; retry |
| Identifier mismatch | Recollect once | Invent a match | Human/payer verification |
| Spending stop | Stop assistant | Invent coverage | Human completes verification |
| Assistant/model failure | Degraded/unavailable | Invent coverage | Human completes verification |
| Emergency | Care first | Delay for insurance | Clinical emergency process |
| Patient disputes result | Record dispute | Override official source by guess | Human/payer verification |
| Clinic sheet vs payer/regulation | Follow payer/regulation | Follow the sheet | Supervisor to correct the sheet |
