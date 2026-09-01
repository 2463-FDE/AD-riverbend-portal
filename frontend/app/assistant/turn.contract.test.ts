// eligibility-assistant-D-45 — the portal's half of the one payload declaration.
// contracts/visit-chat-turn.json is asserted from BOTH suites:
// tests/test_a1_turn_contract.py pins the assistant's pydantic models to it, and
// this file pins the portal's mirrored constants — so the three copies (portal,
// gateway, assistant) cannot drift apart silently.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  PAYERS,
  PRODUCTS,
  QUESTION_TYPES,
  STATES,
  TURN_MODES,
  TURN_OUTCOMES,
  TURN_REASONS,
} from "../lib/types";

const contract = JSON.parse(
  readFileSync(
    resolve(__dirname, "../../../contracts/visit-chat-turn.json"),
    "utf-8"
  )
) as {
  request_fields: Record<string, string[]>;
  enums: Record<string, string[]>;
};

describe("visit-chat turn contract (portal side)", () => {
  it("the four selection menus equal the contract's closed sets", () => {
    expect([...QUESTION_TYPES]).toEqual(contract.enums.question_type);
    expect([...PAYERS]).toEqual(contract.enums.payer);
    expect([...PRODUCTS]).toEqual(contract.enums.product);
    expect([...STATES]).toEqual(contract.enums.state);
  });

  it("the mode, reason and outcome unions equal the contract's sets", () => {
    expect([...TURN_MODES]).toEqual(contract.enums.mode);
    expect([...TURN_REASONS]).toEqual(contract.enums.reason);
    expect([...TURN_OUTCOMES]).toEqual(contract.enums.outcome);
  });

  it("the portal's turn body sends exactly its share of the declared root", () => {
    // The declared root is the ASSISTANT's request; `turns` and `facts` are the
    // gateway's to add from visit memory. What the portal owns is everything
    // else — and nothing else.
    const gatewayOwned = ["turns", "facts"];
    const portalKeys = [
      "emergency",
      "message",
      "payer",
      "product",
      "question_type",
      "state",
    ];
    expect(
      contract.request_fields.root.filter((k) => !gatewayOwned.includes(k)).sort()
    ).toEqual(portalKeys);
  });

  it("a rendered citation carries exactly the declared four fields", () => {
    expect(contract.request_fields.citations).toEqual([
      "document_id",
      "section",
      "title",
      "version",
    ]);
  });
});
