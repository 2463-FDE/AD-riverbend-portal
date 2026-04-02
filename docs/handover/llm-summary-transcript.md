# AI summary — transcript that concerned Dr. Okonkwo

**Patient:** on file with **no medications** recorded.

**Input record sent to the model:**
```
{"name":"James O'Brien","dob":"1958-11-19","mrn":"M5012","notes":"Hearing aid follow-up. No active meds."}
```

**Generated summary returned to the portal (verbatim):**
> Welcome back! Please arrive 15 minutes early and bring your insurance card.
> **Continue metformin as prescribed** and stay hydrated.

The patient is not on metformin. The model invented it. The summary endpoint
returns model output directly — no grounding check, no validation, no
"refuse if unknown."
