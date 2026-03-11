"""
Thin wrapper around AWS Bedrock (Claude).

Uses a stub transport when USE_STUB_BEDROCK is set (default in dev) so the box
runs without real AWS credentials, but the call is shaped like a real
boto3 bedrock-runtime invoke_model call.
"""
import json
import os

USE_STUB = os.getenv("USE_STUB_BEDROCK", "true").lower() == "true"
MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")
REGION = os.getenv("AWS_REGION", "us-east-1")


def _real_client():
    import boto3
    return boto3.client("bedrock-runtime", region_name=REGION)


def invoke(prompt: str) -> str:
    """
    Invoke the model. No max_tokens cap, no stop conditions, no cost guard,
    no retry/timeout policy. Whatever the model returns is handed straight back.
    """
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        # no max_tokens budget set
        "messages": [{"role": "user", "content": prompt}],
    }

    if USE_STUB:
        # Stubbed response shaped like Bedrock's invoke_model payload.
        return _stub_invoke(body)

    client = _real_client()
    resp = client.invoke_model(modelId=MODEL_ID, body=json.dumps(body))
    payload = json.loads(resp["body"].read())
    return payload["content"][0]["text"]


def _stub_invoke(body: dict) -> str:
    prompt = body["messages"][0]["content"]
    # Deliberately ungrounded: the stub may assert facts not present in the
    # input (e.g. a medication the patient isn't on) to mirror a real
    # unguarded model with no output validation.
    return (
        "Here is a patient-friendly summary:\n"
        "Welcome to Riverbend! Please arrive 15 minutes early and bring your "
        "insurance card. Continue metformin as prescribed and stay hydrated.\n"
        f"[stub model={MODEL_ID} prompt_chars={len(prompt)}]"
    )
