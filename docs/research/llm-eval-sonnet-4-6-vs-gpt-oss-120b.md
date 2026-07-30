# LLM Evaluation: Claude Sonnet 4.6 (Bedrock) vs gpt-oss-120B (Bedrock / Ollama)

> Research aside for the Riverbend intake assistant. Evaluated 2026-07-06.
> Scenario constraints: healthcare needs a BAA + in-account data path; finance needs
> auditability and predictable cost at high call volume.

## Comparison

| Criterion | Claude Sonnet 4.6 on Bedrock | gpt-oss-120B (Bedrock serverless / Ollama) |
|---|---|---|
| Model ID | `anthropic.claude-sonnet-4-6` | `openai.gpt-oss-120b-1:0` / `gpt-oss:120b` |
| Price per 1M tokens | $3 in / $15 out | Bedrock: $0.15 in / $0.60 out. Ollama: $0 per-token, but GPU (~80GB VRAM, ≈H100) plus ops staff |
| BAA / HIPAA | Bedrock is HIPAA-eligible; Claude is covered under the AWS BAA (executed via AWS Artifact). Anthropic never sees the data — inference stays in-account | Bedrock-hosted: same AWS BAA coverage. Ollama: no BAA exists — compliance is entirely DIY (VPC isolation, encryption, audit all on you) |
| Data path | Stays in the AWS account/region. No egress to Anthropic | Bedrock: in-account. Ollama: in your VPC — fully local, but you own the whole control surface |
| Auditability | CloudTrail + Bedrock invocation logging, managed guardrails | Bedrock: same CloudTrail path. Ollama: build your own logging/audit; version pinning is trivial (weights frozen) |
| Cost predictability at volume | Per-token, linear, ~25x the gpt-oss rate | Bedrock serverless: per-token, very cheap. Ollama: fixed infra cost — flat and predictable at high volume, wasteful at low |
| Capability | Frontier-tier: strong instruction following, 1M context, tool use, safety behavior — matters for PHI-adjacent intake conversations | Mid-tier open-weight reasoning model; decent but weaker instruction following, higher hallucination risk, no vendor safety tuning |

## Recommendation (Riverbend = healthcare)

**Claude Sonnet 4.6 on Bedrock.**

For a healthcare intake assistant, Claude Sonnet 4.6 on Amazon Bedrock is the right
choice: Bedrock is a HIPAA-eligible service, so PHI flowing through the intake assistant
is covered under the standard AWS BAA (executed via AWS Artifact) with inference staying
entirely inside the customer's AWS account — Anthropic never sees the data — which
satisfies both the BAA and in-account data-path requirements with zero additional
compliance engineering. Self-hosting gpt-oss-120B on Ollama would keep data local but
leaves the entire HIPAA control surface (encryption, access control, audit logging,
incident response) as bespoke work with no BAA counterparty, and even gpt-oss on Bedrock,
while cheap ($0.15/$0.60 vs $3/$15 per million tokens) and BAA-covered, trades away the
frontier-model instruction-following and safety behavior that matter when the assistant
is eliciting symptoms, insurance details, and consent from real patients. Intake volume
is modest and conversation-shaped, so the ~25x per-token premium is a small absolute
cost against the risk of a weaker model mishandling PHI-laden dialogue.

## Counterpoint: the finance profile

A finance client (auditability + predictable cost at high call volume) tilts toward
gpt-oss-120B instead. On Bedrock serverless you keep CloudTrail auditability and pay
~25x less per token; self-hosted on Ollama you get flat infrastructure cost and frozen,
version-pinned weights — no silent model updates, which is a strong audit story.
High-volume simple calls don't need frontier capability.

## Sources

- [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
- [gpt-oss-120b model card — Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-oss-120b.html)
- [AWS re:Post — Bedrock Anthropic models HIPAA compliance](https://repost.aws/questions/QUszPnXyW0RHyJkSt_Th3mcg/aws-bedrock-anthropic-foundational-models-hipaa-compliance)
- [Aptible — Claude BAA coverage and gaps](https://www.aptible.com/hipaa/claude-baa)
- [Taction — BAAs with OpenAI, Anthropic & AWS Bedrock](https://www.tactionsoft.com/blog/baas-with-openai-anthropic-aws-bedrock/)
