export const meta = {
  name: 'audit-nalazi',
  description: 'Audit phase 2: finders for given lenses, then batched adversarial verification (read-only)',
  phases: [
    { title: 'Nalazi', detail: 'one finder per lens' },
    { title: 'Provjera', detail: '2 verify lenses, batched by file' },
  ],
}
const REPO = '/home/user/crypto-bot'
const COMMON = `Repository: ${REPO} (branch at origin/main HEAD 6280a5a, 2026-11-09). READ-ONLY audit: do not modify, create or delete any file in the repo (scratch files only under /tmp/claude-0). The SQLite databases live on the Render disk and are NOT available locally, so judge from code, tests, DNEVNIK.md and README.md. You may run offline tests (python3 -m pytest tests/<file> -q) or small python -c snippets to check logic. Product context: the owner (Jure) wants the Autopilot (/pravi-trade, ui/pravitrade.py + ui/autopilot.py + ui/zivo.py + run_trade.py + trade/ + league/copy.py) to use EXISTING data so that it is fresh, usable, correctly interpreted and profitable, and then to push that same data to Pregled (ui/overview.py), Influenceri (ui/kol.py), Walleti (ui/copytrade.py, wallets/), Tokeni (ui/coins.py, ui/nastoken.py, /tokens page) highlighting it as the freshest and most relevant. Hard rules from CLAUDE.md: tokens under $30k mcap are not analysed; fresh pump.fun tokens are not taken, only bonded ones; real money stays dry until the strategy proves an edge in demo. Write every free-text field in Croatian, concise and concrete, always with file:line references. Work fast: read what you need once, no long deliberation.`

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: { type: 'array', items: { type: 'object', properties: {
      title: { type: 'string', description: 'Croatian, <=12 words' },
      file: { type: 'string' }, line: { type: 'integer' },
      category: { type: 'string', enum: ['nelogičnost', 'svježina', 'interpretacija', 'profit', 'propagacija', 'robusnost', 'testovi', 'koncentracija'] },
      severity: { type: 'string', enum: ['kritično', 'visoko', 'srednje', 'nisko'] },
      claim: { type: 'string', description: 'exact defect statement, Croatian' },
      evidence: { type: 'string', description: 'quoted code lines / numbers / DNEVNIK facts that prove it' },
      fix: { type: 'string', description: 'concrete minimal change, Croatian' },
      profit_impact: { type: 'string', description: 'how this touches real-money results or decision quality' },
    }, required: ['title', 'file', 'line', 'category', 'severity', 'claim', 'evidence', 'fix', 'profit_impact'] } },
  },
  required: ['findings'],
}

const BATCH_VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    verdicts: { type: 'array', items: { type: 'object', properties: {
      idx: { type: 'integer', description: 'the finding index as given' },
      real: { type: 'boolean' },
      confidence: { type: 'number', minimum: 0, maximum: 1 },
      reason: { type: 'string', description: 'Croatian, cite file:line you checked' },
      corrected_claim: { type: 'string', description: 'accurate version if partly right; else empty' },
      severity: { type: 'string', enum: ['kritično', 'visoko', 'srednje', 'nisko'] },
    }, required: ['idx', 'real', 'confidence', 'reason', 'corrected_claim', 'severity'] } },
  },
  required: ['verdicts'],
}

const LENSES = {
  'nelogičnost': 'Logical contradictions and inconsistencies inside the Autopilot path: follow → signal → gates → buy → exit → limits. Hunt: a gate checked in UI but not in run_trade (or vice versa); max_runup/max_mcap read from a different source than where the UI says; tp/sl parsed differently in two places; day limits using different timezone or counting different positions; "ekipa" min_callers semantics vs. the "first caller enters" promise; dry vs live decision differing between pages and the executor; config.json "mode" ignored; defaults diverging between form and executor; unit mistakes (SOL vs USD, % vs fraction, ms vs s).',
  'svježina': 'Stale data presented or used as fresh. Hunt: age filters missing or too wide (signal age, hot_list age, minute-check window, recommendations up to 6 h used for "sada"), caches (DexScreener batch cache, pagecache, kv) whose TTL exceeds the refresh promise (1 s / 2 s / 60 s), timestamps compared in different zones or naive vs aware, "updated" labels showing read time instead of data time, data produced by a loop that in reality runs far less often than the page claims (use the render-live map: GeckoTerminal 403s, brava waits, KOL round duration), fallback paths that silently reuse old rows.',
  'interpretacija': 'Metrics computed or read wrongly so decisions rest on a false picture. Hunt: success rates with survivorship/lookahead bias (entry price taken after the call, wick vs close, stop checked after target in the same candle), denominators excluding failed/unmeasured calls, rug flags that flip meaning, percent change fields from DexScreener mis-assigned (m5/h1/h6/h24), MC vs FDV confusion, liquidity vs volume, "dokazan dvaput" definitions, PnL excluding fees or failed buys, expectation of +15 % derived from a different success definition than the exit target in use, league/demo PnL shown next to real PnL without saying which is which.',
  'profit': 'Where existing data could make the Autopilot more profitable but is not used, or where current logic destroys edge. Hunt: minute-check success stats (+10 % before stop, stop-first rate) not gating or sizing real entries; hot_list not used at buy time; exit target fixed at tp_default regardless of caller statistics; slippage/cost check vs expected move (max_cost_pct – applied?); max_runup computed from h1 change instead of change-since-call; buying the same token twice across follows; dry-run PnL not comparable with live costs (fees, priority fees, slippage); demo "edge proven" criterion absent or never evaluated; sizing ignoring liquidity; sell_check semantics; what the DNEVNIK numbers (KOL pozivi +294 % but −$580 without the best trade) imply for real-money rules.',
  'propagacija': 'How Autopilot-grade live data should flow to Pregled, Influenceri, Walleti, Tokeni and where today those pages show older, differently computed or contradictory numbers. Hunt: the same metric (caller success, wallet proven, token state, rug verdict) computed in two modules with different definitions; pages reading a slow table while Autopilot has a fresher kv/live list; missing surfacing of zivo list, Zovu sada, hot_list, minute check, open positions, follows on those pages; links that should open the same token pop-up; labels saying "sada" for data hours old. Propose for each page exactly which Autopilot data to surface and from which function.',
  'robusnost': 'Robustness/performance defects that make data late or missing: network calls inside UI request handlers (blocking the 1 s refresh), pages built for 60 s, DB lock contention between writers (which DBs run_trade, run_live, run_kol, UI open), the global lock making light jobs wait, UI memory growth (174→259 MB in minutes on 9.11.), exceptions swallowed so a feed silently stops (GeckoTerminal 403 handled?), missing retries/backoff, watchdog kills restarting the trade loop mid-order, start order after deploy (trade loop up before webhook/live feeds).',
  'koncentracija': 'Owner rule (9.11., from @StalkHQ): holder COUNT means nothing – one person can control thousands of wallets; a token with 30k holders crashed 95 % in an hour; what matters is WHO holds the supply. Audit how the system treats holders and supply concentration on the path to a real-money buy. Hunt: (1) every place holder count or holder growth is a POSITIVE signal (hype/pulse.py rast_holdera/organski, ui/confidence.py holders_ok/rast_holdera, dugo holderi_30d, ui/coins.py, tiers/) without a concentration check – that is exactly the deception the rule names; (2) whether the Autopilot buy path (ui/zivo.py candidates/gate, run_trade.py, trade/executor.py, league/copy.py _rugged, kol/converge.py, the "Kupi" live check in ui/pravitrade.py) checks top10 %, bundle %, sniper %, insider %, dev %, fresh-wallet % BEFORE a real entry, or only the hype score does (ui/criteria.py says they are weights, not thresholds; topcheck/safety.py has TOP10_FAIL 60 / WARN 35 – is "warn" blocking anything? is topcheck data even present for a token called "now", given run_top.py checks only the top 20 recommendations every 3 min and the full Helius rug filter runs at most every 12 h per token, 30 a day?); (3) ui/confidence.py:45 notes a 31.10. retrospective "top10 > 45 % went 5x MORE often, bundle cut would drop 44 % of winners, so concentration is noted, not punished" – judge whether that upside statistic is a valid reason to ignore concentration for REAL money with a −20 % stop (crash risk, exit liquidity: can the position be sold if a top holder dumps? position size vs liquidity vs largest holder), and propose a concrete real-money rule (e.g. hard gate / size cut / reason shown in the token pop-up) using data the system already stores (rug.db, topcheck.db, RugCheck top holders with insider flags, pump.fun top10HoldersPercent/bundlerOwnedPercent/snipersOwnedPercent/devHoldingsPercent); (4) freshness of that concentration data at buy time and whether the token pop-up "U REDU ZA ULAZ / NE KUPUJ" shows who holds the supply.',
  'testovi': 'Tests vs product rules. Read tests/ about pravitrade, autopilot, zovu, trade, minute, converge, zivo, audit_20261104. Hunt: assertions that lock in wrong behaviour; missing tests for money-critical paths (max_mcap/max_runup gate, day limits at Zagreb midnight, dry/live decision, ekipa first-caller entry, exit target); tests that mock away the very check they claim to test; tests that would fail if the fixes implied by other lenses were made.',
}

const VERIFY = [
  { key: 'kod', ask: 'Open each cited file at the cited line (and callers/callees). Does the code REALLY do what the claim says? Trace actual values. If the claim misreads the code, refute it. Default to real=false when the evidence does not hold up line by line.' },
  { key: 'kontekst', ask: 'Read DNEVNIK.md, README.md and the comments around each cited code. (a) Is this an intentional, documented decision (then not a defect unless it contradicts a CLAUDE.md rule or loses money)? Was it already handled elsewhere? (b) If true, does it matter for fresh/correct/profitable Autopilot data or for Pregled/Influenceri/Walleti/Tokeni? Is the fix safe and minimal (name tests/ that would be affected)? Set real=false if intentional-and-harmless, negligible, or the fix is dangerous. Set severity to your own judgement.' },
]

const lensKeys = args.lenses
function chunksByFile(list) {
  const byFile = {}
  list.forEach((f, idx) => { (byFile[f.file] = byFile[f.file] || []).push({ ...f, idx }) })
  const chunks = []
  Object.values(byFile).forEach(arr => { for (let i = 0; i < arr.length; i += 4) chunks.push(arr.slice(i, i + 4)) })
  // merge tiny chunks (1 finding) pairwise to cut agent count
  const out = []; let acc = []
  for (const c of chunks) { if (c.length >= 3) { out.push(c); continue } acc.push(...c); if (acc.length >= 3) { out.push(acc); acc = [] } }
  if (acc.length) out.push(acc)
  return out
}
const fmt = f => `[idx ${f.idx}] ${f.title}\n  mjesto: ${f.file}:${f.line}\n  kategorija/težina: ${f.category}/${f.severity}\n  tvrdnja: ${f.claim}\n  dokaz: ${f.evidence}\n  popravak: ${f.fix}\n  profit: ${f.profit_impact}`

const results = {}
await pipeline(lensKeys,
  k => agent(`${COMMON}

You are a finder with the lens "${k}". ${LENSES[k]}

FIRST read the file ${args.maps_file} (six subsystem maps written by colleagues: autopilot, signali, preporuke, stranice, pogon, render-live measured from Render logs; 150 "sumnjivo" leads with file:line). Treat them as leads – verify everything yourself in the code before reporting.

Method: read the code at the places the maps point to and anywhere else your lens requires; for each defect quote the lines. Report only defects you personally confirmed in the code (or in the Render-log facts of the maps). Prefer fewer, sharper findings: 6–14. Each fix minimal and concrete (which function, what changes). profit_impact says how it touches real money or decision quality.`, { label: `nalaz:${k}`, phase: 'Nalazi', schema: FINDINGS_SCHEMA, effort: 'high' }),
  async (found, k) => {
  const list = (found && found.findings) || []
  log(`nalazi ${k}: ${list.length}`)
  if (!list.length) { results[k] = { confirmed: [], rejected: [] }; return }
  const chunks = chunksByFile(list)
  const votes = list.map(() => [])
  await parallel(chunks.flatMap(chunk => VERIFY.map(v => () => agent(`${COMMON}

You are an adversarial verifier with the lens "${v.key}". Try to REFUTE each of these findings (lens "${k}"):

${chunk.map(fmt).join('\n\n')}

${v.ask} Return one verdict per idx, citing the lines you checked.`, { label: `provjera:${k}:${v.key}:${chunk[0].file.split('/').pop()}`, phase: 'Provjera', schema: BATCH_VERDICT_SCHEMA, effort: 'high' }).then(r => {
    if (!r) return
    r.verdicts.forEach(vd => { if (votes[vd.idx]) votes[vd.idx].push({ lens: v.key, ...vd }) })
  }))))
  const confirmed = [], rejected = []
  list.forEach((f, idx) => {
    const vs = votes[idx]
    const yes = vs.filter(x => x.real).length
    const item = { ...f, votes: vs }
    if (vs.length >= 2 ? yes >= 2 : yes >= 1) confirmed.push(item); else rejected.push(item)
  })
  results[k] = { confirmed, rejected }
  log(`provjera ${k}: ${confirmed.length} potvrđeno, ${rejected.length} odbačeno`)
})
return results
