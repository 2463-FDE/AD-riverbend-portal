// regression-proof.js — verify-stack §4's regression proof, executed in parallel worktrees.
//
// Division of labor (verify-stack §4 is authoritative): the MAIN THREAD gathers the
// refs, files, targeted tests and expected red counts per §4's procedure — this
// workflow only executes them. It decides nothing about what "proof" means for a PR.
//
// Preconditions (the invoking skill owns these):
//   - The round's work is COMMITTED. Worktrees materialize the DEFAULT-BRANCH tip,
//     not the session branch — committed-but-unpushed work is invisible at start.
//     Unpushed commits ARE reachable via the shared object store, so every layer's
//     reverts list must FIRST materialize branch state via ordered
//     `git checkout <branch-ref> -- <files>`, then apply the layer's own
//     revert/mutation. Script logic unchanged — it already executes ordered
//     checkouts; this is the args-construction contract.
//   - The test image is pre-built from the main checkout:
//       docker build -q -t riverbend-test:py312 -f Dockerfile.test .
//     Parallel-safety verified 2026-08-05: Dockerfile.test COPYs only
//     requirements-dev.txt (repo is bind-mounted at run time), so each agent's
//     `make test-docker` build is a cache no-op on the shared tag; the runs
//     themselves use `docker run --rm` with no fixed name and no ports.
//
// Worktrees contain tracked files only: no CLAUDE.md, no .claude/ — by design
// (post-descope). The layer agents are mechanical, so their prompts below are
// self-contained. A proof that needs local tooling uses §4's manual fallback.
//
// args shape:
// {
//   layers: [
//     { layer: "A" | "B" | "mutation" | <label>,
//       // exactly one of:
//       reverts: [ { ref: "<sha/ref>", files: ["path", ...] }, ... ],
//       mutation: "<exact one-edit instruction, incl. file and line>",
//       tests: "<pytest args, e.g. tests/test_x.py -q>",
//       expected_red: <int>   // failed + errors the layer must produce
//     }, ...
//   ]
// }
//
// Returns { overall: "PASS" | "FAIL", rows: [...] }. Any row whose actual red
// count differs from expected is a hard fail of the WHOLE proof. The comparison
// is plain JS below — deterministic checks stay deterministic; no judgment agent.

export const meta = {
  name: 'regression-proof',
  description: 'verify-stack §4 regression proof: parallel worktree agents revert/mutate per layer, run targeted container tests, count reds; verdict computed in-script',
  phases: [{ title: 'Prove', detail: 'one Haiku worktree agent per proof layer' }],
}

const LAYER_SCHEMA = {
  type: 'object',
  properties: {
    layer: { type: 'string' },
    expected_red: { type: 'integer' },
    actual_red: { type: 'integer' },
    verdict: { type: 'string', enum: ['pass', 'fail'] },
    notes: { type: 'string', description: 'worktree path, HEAD sha, verbatim pytest summary line, anything unexpected' },
  },
  required: ['layer', 'expected_red', 'actual_red', 'verdict', 'notes'],
}

// ---- args validation (fail loud, before spawning anything) ----
// PERMANENT guard: args may arrive as a parsed object OR a JSON-encoded string
// depending on the harness path (observed 2026-08-05: string, which killed the
// first dry run). Must accept both — do not simplify this away.
if (typeof args === 'string') {
  try { args = JSON.parse(args) } catch (e) {
    throw new Error('regression-proof: args is a string and not valid JSON: ' + e.message)
  }
}
if (!args || !Array.isArray(args.layers) || args.layers.length === 0) {
  throw new Error('regression-proof: args.layers must be a non-empty array — see header comment for shape')
}
for (const l of args.layers) {
  if (!l.layer) throw new Error('regression-proof: every layer needs a "layer" label')
  const hasReverts = Array.isArray(l.reverts) && l.reverts.length > 0
  const hasMutation = typeof l.mutation === 'string' && l.mutation.length > 0
  if (hasReverts === hasMutation) {
    throw new Error(`regression-proof: layer "${l.layer}" must have exactly one of reverts / mutation`)
  }
  if (hasReverts && l.reverts.some(r => !r.ref || !Array.isArray(r.files) || r.files.length === 0)) {
    throw new Error(`regression-proof: layer "${l.layer}" has a revert entry missing ref or files`)
  }
  if (typeof l.tests !== 'string' || !l.tests) {
    throw new Error(`regression-proof: layer "${l.layer}" needs "tests" (pytest args)`)
  }
  if (!Number.isInteger(l.expected_red) || l.expected_red < 0) {
    throw new Error(`regression-proof: layer "${l.layer}" needs a non-negative integer expected_red`)
  }
}

function layerPrompt(l) {
  const change = l.mutation
    ? `2. Apply EXACTLY this edit and nothing else — no other change, however small:
${l.mutation}`
    : `2. Revert files. For each entry below, run \`git checkout <ref> -- <file>\` per file:
${l.reverts.map(r => r.files.map(f => `   git checkout ${r.ref} -- ${f}`).join('\n')).join('\n')}
   If git errors that a path did not exist at that ref ("pathspec ... did not
   match"), DELETE that file instead (rm <file>) — absence at the ref is the
   intended pre-fix state, not an error to work around.`

  return `You are a mechanical test-runner agent for a regression proof (layer "${l.layer}").
Your working directory is a disposable git worktree of the riverbend repo,
containing tracked files only — no CLAUDE.md, no .claude/ tooling exists here;
this prompt is your complete instruction set. Do not explore the repo, do not
fix or improve anything, do not read anything under logs/. Mechanical steps only:

1. Run \`git rev-parse --show-toplevel\` and \`git rev-parse HEAD\`; record both
   in your notes.
${change}
3. Run: make test-docker ARGS="${l.tests}"
   The image riverbend-test:py312 is pre-built, so the build line is a cache
   no-op. The test run may take 10-60s; that is normal. Expect it to be RED —
   a nonzero make exit here is the point, not a problem to debug.
4. From pytest's final summary line, compute actual_red = failed + errors
   (a collection error counts as red). Quote the summary line VERBATIM in notes.
5. Return structured output:
   layer = "${l.layer}", expected_red = ${l.expected_red}, actual_red as counted,
   verdict = "pass" if actual_red == ${l.expected_red} else "fail",
   notes = worktree path + HEAD + verbatim summary line + anything unexpected.
   If actual_red != expected, do NOT investigate or rerun — report and stop.`
}

phase('Prove')
log(`regression-proof: ${args.layers.length} layer(s) — ${args.layers.map(l => l.layer).join(', ')}`)

const results = await parallel(args.layers.map(l => () =>
  agent(layerPrompt(l), {
    label: `layer:${l.layer}`,
    phase: 'Prove',
    schema: LAYER_SCHEMA,
    model: 'haiku',        // mechanical layer runs are Haiku-tier by doctrine
    isolation: 'worktree',
  })
))

// Verdict is computed HERE, from the agent-reported counts vs the args'
// expectations — the agent's own verdict field is informational only.
const rows = args.layers.map((spec, i) => {
  const r = results[i]
  if (!r) {
    return { layer: spec.layer, expected_red: spec.expected_red, actual_red: null,
             verdict: 'FAIL', notes: 'agent returned nothing (skipped or terminated) — rerun this layer' }
  }
  const pass = r.actual_red === spec.expected_red
  let notes = r.notes
  if ((r.verdict === 'pass') !== pass) notes += ' [agent verdict disagreed with script comparison — script wins]'
  return { layer: spec.layer, expected_red: spec.expected_red, actual_red: r.actual_red,
           verdict: pass ? 'pass' : 'FAIL', notes }
})

const overall = rows.every(r => r.verdict === 'pass') ? 'PASS' : 'FAIL'
log(`regression-proof verdict: ${overall}`)
return { overall, rows }
