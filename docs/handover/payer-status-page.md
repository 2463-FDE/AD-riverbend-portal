# ACME Clearinghouse — Status Page (saved snapshot)

**Incident: Eligibility (270/271) endpoint degradation**
- **Window:** Tuesday 09:02–09:21 (19 minutes)
- **Impact:** Elevated latency and timeouts on the `/v1/eligibility` endpoint.
- **Resolution:** Upstream connectivity restored 09:21. No data loss.

---
p95 latency for `/intake` (portal, same week): flat ~600ms all week, with a
single 20-minute spike past 30s Tuesday morning — overlapping the window above.
