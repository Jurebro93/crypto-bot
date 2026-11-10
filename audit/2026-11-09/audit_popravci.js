export const meta = {
  name: 'audit-popravci',
  description: 'Fix one group of verified audit findings in crypto-bot (owned files only), adversarial review, re-fix',
  phases: [
    { title: 'Popravak', detail: 'one implementer for the group' },
    { title: 'Pregled', detail: 'adversarial reviewer of the diff' },
    { title: 'Dorada', detail: 'implementer fixes blocking review items' },
  ],
}
const REPO = '/home/user/crypto-bot'
const SCRATCH = '/tmp/claude-0/-home-user/4912361d-d525-5b3e-b714-652a838e02b7/scratchpad'
const RULES = `Repository: ${REPO}, branch ccr-232765a7-33e8r8 (= origin/main 6280a5a). Work directly in the working tree. NEVER run git commit/checkout/reset/stash/clean; the orchestrator commits. Baseline: \`python3 -m unittest discover -s tests\` → 878 tests OK in ~40 s (all deps installed). Tests are unittest style, offline, no network.
Product rules that every change must respect (CLAUDE.md + owner decisions 9.11.):
- trade/config.json stays "mode": "dry"; TRADE_LIVE/armed/is_live semantics unchanged; nothing may make a live swap easier.
- Tokens under $30k mcap are never bought automatically; only bonded pump.fun tokens (a token priced only via the Jupiter bonding-curve fallback is NOT bonded).
- Holder COUNT is never a positive signal; supply concentration (top10 %, bundle %, insider %, dev %) is a risk. A concentration gate may block only on KNOWN bad data (never "no data → no buy", which would kill every fresh KOL copy); missing data must be shown as "nepoznato", never as "prolazi"/"u redu".
- No new paid API calls, no new network calls inside 1-second UI fragment handlers (background refresh instead), DexScreener live TTL 2–5 s (not 1 s: the 300/min IP limit is shared by all processes), scanners keep 60 s.
- Every tpsl follow without an explicit stop gets the default stop −20 % (same threshold as kol/minute.py); TP/SL computed from the effective entry when available.
- Time: compare UTC epoch everywhere; display data time, not render time; day limits for demo and real money use the same day boundary (Europe/Zagreb, trade/executor.DAY_TZ).
- Code style: match the file (English code comments with the date and owner, e.g. "# 9.11. (audit): ...", Croatian UI/log strings, no new dependencies). Keep diffs minimal and local; do not reformat.
- Tests: for every behavioural change add or adjust an offline unittest. New assertions go into a NEW file tests/test_audit_20261109_<group>_offline.py (so parallel groups never edit the same test file); edit an EXISTING test file only when your change breaks it AND that file is in your ownership list. If a change you need touches a file outside your ownership (code or test), do NOT edit it: append a precise note (file, line, what, why, which finding) to ${SCRATCH}/handoff_<group>.md.
- Finish only when \`python3 -m unittest discover -s tests\` is fully green (or the only failures are in files you may not touch and are listed in your handoff note with the reason).`

const SUMMARY_SCHEMA = {
  type: 'object',
  properties: {
    changes: { type: 'array', items: { type: 'object', properties: {
      findings: { type: 'array', items: { type: 'string' }, description: 'P-ids addressed' },
      file: { type: 'string' }, what: { type: 'string', description: 'Croatian, 1-3 sentences' },
    }, required: ['findings', 'file', 'what'] } },
    partial_or_skipped: { type: 'array', items: { type: 'object', properties: {
      finding: { type: 'string' }, why: { type: 'string' }, suggestion: { type: 'string' },
    }, required: ['finding', 'why', 'suggestion'] } },
    tests_added: { type: 'array', items: { type: 'string' } },
    full_suite: { type: 'string', description: 'exact last lines of unittest discover output' },
    handoff_written: { type: 'boolean' },
    notes_for_dnevnik: { type: 'array', items: { type: 'string' }, description: 'Croatian one-liners for the diary: what changed and why (no env names/keys/addresses)' },
  },
  required: ['changes', 'partial_or_skipped', 'tests_added', 'full_suite', 'handoff_written', 'notes_for_dnevnik'],
}
const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    blocking: { type: 'array', items: { type: 'object', properties: {
      file: { type: 'string' }, line: { type: 'integer' }, problem: { type: 'string' }, fix: { type: 'string' },
    }, required: ['file', 'line', 'problem', 'fix'] } },
    suggestions: { type: 'array', items: { type: 'string' } },
    verdict: { type: 'string', description: 'Croatian, 2-4 sentences' },
  },
  required: ['blocking', 'suggestions', 'verdict'],
}

const g = args.group
const implPrompt = (extra) => `${RULES}

You are the implementer for group "${g}". OWNERSHIP – you may edit ONLY these files (plus the new test file tests/test_audit_20261109_${g.replace(/[^a-z0-9]/g, '_')}_offline.py): ${args.owned}
Explicitly NOT yours (other agents edit them in parallel): ${args.forbidden}

Read ${args.findings_file} fully (chunks of ~300 lines). For each finding, implement the minimal fix proposed under "popravak", but ALWAYS apply the verifier votes' corrections and warnings (ISPRAVAK / oprez / pogođeni testovi) – they override the finder's proposal when they conflict. Where a finding is a larger design proposal, implement the safe minimal version now and put the rest into partial_or_skipped with a concrete suggestion. Read the surrounding code before editing; follow callers/callees so a changed signature or return shape does not break other modules (grep the repo). Prefer adding an optional parameter / new helper over changing existing semantics used elsewhere.

Order of work: money-critical first (gates in the buy path, stops, limits), then freshness, then interpretation/display, then tests-only findings. After each file, run its tests (python3 -m unittest tests.test_<x>_offline). At the end run the full suite and fix what you broke (within ownership). Then write handoff notes if any, and return the summary.${extra || ''}`

phase('Popravak')
const impl = await agent(implPrompt(''), { label: `popravak:${g}`, phase: 'Popravak', schema: SUMMARY_SCHEMA, effort: 'high' })
log(`popravak ${g}: ${impl ? impl.changes.length + ' promjena, suite: ' + (impl.full_suite || '').slice(-80) : 'nema rezultata'}`)

phase('Pregled')
const review = await agent(`${RULES}

You are an adversarial reviewer for group "${g}". Run \`cd ${REPO} && git diff -- ${args.owned_paths} && git status --short\` and read every changed hunk in full context (open the files). Also read ${args.findings_file} to know what each change was supposed to do. Hunt for: (1) anything that makes a live swap more likely or weakens a money gate; (2) a gate that would block everything in practice (e.g. "no data → skip", or a mcap/liq check against a value that is None for most fresh tokens – check copy.market() return shape); (3) unit/sign/timezone mistakes; (4) changed function signatures or return shapes that break callers or tests elsewhere (grep); (5) new network calls in UI request handlers, new paid API usage, TTL below 2 s; (6) Croatian UI strings broken or leaking env names/keys/addresses; (7) tests that mock away the very check they claim to test. Run \`python3 -m unittest discover -s tests\` yourself and report the exact tail. Blocking = must be fixed before commit; suggestions = nice to have.

Implementer's summary: ${JSON.stringify(impl)}`, { label: `pregled:${g}`, phase: 'Pregled', schema: REVIEW_SCHEMA, effort: 'high' })
log(`pregled ${g}: ${review ? review.blocking.length + ' blokirajućih' : 'nema rezultata'}`)

let fix2 = null
if (review && review.blocking.length) {
  phase('Dorada')
  fix2 = await agent(implPrompt(`

A reviewer found BLOCKING problems in your group's diff; fix exactly these (and anything they break), re-run the full suite, and return an updated summary covering the whole group's work (previous summary: ${JSON.stringify(impl)}):
${review.blocking.map((b, i) => `${i + 1}. ${b.file}:${b.line} – ${b.problem} → ${b.fix}`).join('\n')}
Reviewer suggestions (apply if cheap and safe): ${review.suggestions.join(' | ')}`), { label: `dorada:${g}`, phase: 'Dorada', schema: SUMMARY_SCHEMA, effort: 'high' })
}
return { group: g, summary: fix2 || impl, review }
