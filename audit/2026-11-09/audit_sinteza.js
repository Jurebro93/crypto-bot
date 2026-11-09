export const meta = {
  name: 'audit-sinteza',
  description: 'Audit phase 3: synthesise the Croatian audit report from verified findings (read-only)',
  phases: [{ title: 'Sinteza', detail: 'one synthesiser agent' }],
}
const REPO = '/home/user/crypto-bot'
const COMMON = `Repository: ${REPO} (branch at origin/main HEAD 6280a5a, 2026-11-09). READ-ONLY: do not modify, create or delete any file in the repo. Databases are not available locally. Product context: the owner (Jure) wants the Autopilot (/pravi-trade) to use EXISTING data so it is fresh, usable, correctly interpreted and profitable, then push that data to Pregled, Influenceri, Walleti, Tokeni as the freshest/most relevant. Hard rules (CLAUDE.md): tokens under $30k mcap are not analysed; only bonded pump.fun tokens; real money stays dry until the strategy proves an edge in demo; holder COUNT is not a signal, supply concentration (who holds) is. Write in Croatian, concise, concrete, every claim with file:line; separate "Provjereno" from "Pretpostavka"; no env names, keys, wallet addresses or costs beyond what DNEVNIK.md already states; no praise, no filler.`

phase('Sinteza')
const report = await agent(`${COMMON}

You are the synthesiser. FIRST read these two files fully (use Read with offset/limit in chunks of ~400 lines until the end): ${args.maps_file} (six subsystem maps incl. Render-log measurements; the "### MAPA render" section holds the measured numbers for chapter 2) and ${args.findings_file} (85 verified findings, compact: claim, verifier-corrected claim, fix, impact, caveats, affected tests; then 12 rejected with reasons). The full evidence and votes are in ${args.findings_full} if you need to resolve a contradiction; do not start a new audit.

Write the final audit report as Markdown with EXACTLY this structure:
# Audit Autopilota: podaci, svježina, interpretacija, profit (9.11.2026.)
## 1. Sažetak u 10 redaka
## 2. Što danas stvarno radi (izmjereno na Renderu, 8.11. 16:00 – 9.11. 16:10 UTC) — numbers from the render map; "Provjereno" vs "Pretpostavka"
## 3. Nalazi po prioritetu — one Markdown table: # | težina | kategorija | nalaz (1 rečenica) | mjesto | popravak (1 rečenica) | učinak na novac/odluke. Merge duplicates across lenses (same file+topic → one row, keep the sharpest wording, use verifier corrected_claim where given). Order: money risk first (what can lose real money or buy a forbidden token), then freshness, then interpretation, then propagation, then robustness/tests. Number rows N1, N2, …
## 4. Plan: podaci u Autopilotu → svježi, ispravno protumačeni, profitabilni — ordered steps grouped A) hitno (novac), B) svježina, C) interpretacija, D) profit (gating/sizing/exits koristeći minutnu provjeru, hot_list i koncentraciju supplyja). Each step: što · gdje (file:function) · zašto (reference N-rows) · koji test (existing tests/ file to extend or new offline test). Include an explicit "Kriterij dokazanog edgea u demu" proposal computable from data the system already journals (league.db trades, prijedlog_log, minute.db, strat robust), with concrete thresholds and a note where it would be checked in code before a live buy.
## 5. Propagacija na Pregled / Influenceri / Walleti / Tokeni — per page: which Autopilot data to surface (which function/kv), replacing which older/divergent number, and how to label freshness (data time, not render time).
## 6. Odbačeni nalazi (zašto) — one line each.
## 7. Pretpostavke i što nismo mogli provjeriti
## 8. Što dalje — 3 lines: what Jure must decide (yes/no questions), what the tool can do alone.

Return ONLY the Markdown report.`, { label: 'sinteza', phase: 'Sinteza', effort: 'high' })
return { report }
