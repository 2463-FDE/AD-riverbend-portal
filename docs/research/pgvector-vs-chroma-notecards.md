# Notecards — pgvector vs Chroma (Riverbend)

> Speaker notes for `pgvector-vs-chroma-deck.html`. One card per slide.
> Slides stay sparse; say the rest. ~5–6 min talk.

---

## Card 1 — Title: "Where do the vectors live?"

We're adding document retrieval / RAG. That needs a vector store. Two real options:
put vectors in the **Postgres we already run** (pgvector extension), or stand up
**Chroma DB** as a dedicated vector database. I looked at both. The decision isn't
close, and it turns on one thing — we handle **PHI**. Recommendation up front:
**pgvector**.

---

## Card 2 — The constraint: we are a HIPAA covered entity

Frame the whole decision before comparing features.
- Our Postgres 15 is already the **system of record for patient data** — it's inside our
  compliance boundary today, under our encryption, access control, and audit.
- So the bar any vector store must clear: **do not open a new PHI path, and never send
  PHI to a vendor without a BAA.**
- If a "better" vector DB fails that bar, it's disqualified regardless of features. Hold
  that thought for the next two slides.

---

## Card 3 — Verdict matrix

Walk down, don't read it out. Land these:
- **HIPAA/BAA, residency, new vendor** — pgvector green, Chroma red. This is the whole game.
- **Integration** — pgvector is one extension and a column; Chroma means a new client, and
  embeddings get **synced out of Postgres** into a second store.
- **Scale** — one honest point in Chroma's favor: it's built to scale past a single Postgres
  node. Flag it, then say the quiet part — *our corpus is clinic-scale, so we never reach that
  ceiling.* Chroma wins the one column that doesn't matter here.

---

## Card 4 — The decisive fact (dwell here)

This is the slide that ends the debate.
- I checked Chroma's **own** pages — pricing, security, docs. They advertise **SOC 2 Type II
  and nothing else. No HIPAA. No BAA.**
- pgvector doesn't have its own posture — it **inherits Postgres's**. On managed RDS/Aurora
  that's HIPAA-eligible under the AWS BAA (since 2016); on our current Postgres the embeddings
  just live under the PHI controls we already run.
- Say it plainly: **routing patient records through managed Chroma = PHI to a third party with
  no BAA = a HIPAA violation.** BYOC could keep data in our VPC, but it's a custom Enterprise
  contract and *still* no advertised BAA.
- If asked "could we get a BAA from Chroma?" — maybe via a custom Enterprise deal, but it's not
  offered today, and that's procurement + legal we don't need to take on.

---

## Card 5 — Recommendation + cost

- Restate: **pgvector, in our existing Postgres.** No new vendor, no new data path, no new BAA,
  one extension.
- Cost: extension is **free** — we already pay for the Postgres. Chroma is **$250/mo (Team) +
  usage**, or custom Enterprise for the BYOC/SLA tier, plus per-GiB write/storage/egress.
- The clincher isn't even cost — it's that pgvector adds **zero new PHI surface**. Cheapest
  option also happens to be the compliant one.

---

## Card 6 — When Chroma wins (counterpoint)

Show I'm not just anchoring on the familiar tool.
- Chroma is genuinely better for **scale-first, non-regulated** work: hundreds of millions to
  billions of vectors, high throughput, purpose-built filtering, serverless scaling.
- It's the right call **when** the corpus is non-PHI (SOC 2 is enough), **or** you run BYOC in
  your own VPC under an Enterprise contract.
- Neither is Riverbend today. So: revisit Chroma if we ever build a large non-PHI corpus or
  outgrow pgvector's scale ceiling. Until then, pgvector.

---

### Likely Q&A
- *"Isn't a dedicated vector DB faster?"* At our scale, pgvector's HNSW is plenty; the
  bottleneck is embeddings + LLM latency, not the index.
- *"What if we outgrow it?"* We'd see it in query latency first; migrating out of Postgres later
  is a known path. Don't pay that complexity now.
- *"Self-hosted Chroma (OSS, free)?"* Keeps data in-account, but it's a **new system we operate**
  — new backups, HA, patching, monitoring — for capability we don't need. pgvector reuses ops we
  already run.
