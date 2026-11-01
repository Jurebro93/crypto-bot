// Naš token: launching from the player's own Phantom. Served at /nas-token/launch.js, used by the project page.
// Nothing secret ever reaches the server: Phantom signs, the one-off mint keypair lives only in this browser tab.
// The two builders take the Solana libraries as arguments so the same code runs in the page (esm.sh) and in the
// offline test (npm).

export const METADATA_PROGRAM = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s";

function borshStr(s) {
  const b = new TextEncoder().encode(s);
  const out = new Uint8Array(4 + b.length);
  new DataView(out.buffer).setUint32(0, b.length, true);
  out.set(b, 4);
  return out;
}

function concat(parts) {
  const n = parts.reduce((a, p) => a + p.length, 0);
  const out = new Uint8Array(n);
  let i = 0;
  for (const p of parts) { out.set(p, i); i += p.length; }
  return out;
}

// Metaplex CreateMetadataAccountV3 (discriminator 33): name, symbol, uri, no royalties/creators/collection/uses.
export function metadataIx(web3, { mint, owner, name, symbol, uri, mutable = true }) {
  const pid = new web3.PublicKey(METADATA_PROGRAM);
  const [pda] = web3.PublicKey.findProgramAddressSync(
    [new TextEncoder().encode("metadata"), pid.toBytes(), mint.toBytes()], pid);
  const data = concat([new Uint8Array([33]), borshStr(name), borshStr(symbol), borshStr(uri),
    new Uint8Array([0, 0]),          // seller fee 0 (u16)
    new Uint8Array([0, 0, 0]),       // creators, collection, uses: None
    new Uint8Array([mutable ? 1 : 0]),
    new Uint8Array([0])]);           // collection details: None
  return {
    pda,
    ix: new web3.TransactionInstruction({
      programId: pid,
      keys: [
        { pubkey: pda, isSigner: false, isWritable: true },
        { pubkey: mint, isSigner: false, isWritable: false },
        { pubkey: owner, isSigner: true, isWritable: false },
        { pubkey: owner, isSigner: true, isWritable: true },
        { pubkey: owner, isSigner: true, isWritable: false },
        { pubkey: web3.SystemProgram.programId, isSigner: false, isWritable: false },
      ],
      data,
    }),
  };
}

// Our own SPL token in one transaction: mint account, whole supply to the owner's wallet, Metaplex metadata, then
// mint and freeze authority switched off for good (what our anti-rug filter and every other bot checks first).
export function buildSplTx(web3, spl, { owner, mintKp, decimals, supply, name, symbol, uri, blockhash,
                                        rentLamports = 1461600 }) {
  const mint = mintKp.publicKey;
  const ata = spl.getAssociatedTokenAddressSync(mint, owner);
  const amount = BigInt(supply) * 10n ** BigInt(decimals);
  const md = metadataIx(web3, { mint, owner, name, symbol, uri });
  const tx = new web3.Transaction({ feePayer: owner, recentBlockhash: blockhash });
  tx.add(
    web3.SystemProgram.createAccount({ fromPubkey: owner, newAccountPubkey: mint, space: spl.MINT_SIZE,
                                       lamports: rentLamports, programId: spl.TOKEN_PROGRAM_ID }),
    spl.createInitializeMint2Instruction(mint, decimals, owner, owner),
    spl.createAssociatedTokenAccountIdempotentInstruction(owner, ata, owner, mint),
    spl.createMintToInstruction(mint, ata, owner, amount),
    md.ix,
    spl.createSetAuthorityInstruction(mint, owner, spl.AuthorityType.MintTokens, null),
    spl.createSetAuthorityInstruction(mint, owner, spl.AuthorityType.FreezeAccount, null),
  );
  tx.partialSign(mintKp);
  return { tx, mint: mint.toBase58(), metadata: md.pda.toBase58() };
}

// ---------- page --------------------------------------------------------------------------------------------------

function say(el, text, bad) {
  el.textContent = text;
  el.style.color = bad ? "var(--bad)" : "";
}

async function rpc(net, method, params) {
  const r = await fetch("/nas-token/rpc", { method: "POST", headers: { "Content-Type": "application/json" },
                                            body: JSON.stringify({ net, method, params }) });
  const j = await r.json();
  if (j.error) throw new Error(typeof j.error === "string" ? j.error : JSON.stringify(j.error));
  return j.result;
}

async function confirm(net, sig, el) {
  for (let i = 0; i < 40; i++) {
    const st = await rpc(net, "getSignatureStatuses", [[sig]]);
    const s = st && st.value && st.value[0];
    if (s && s.err) throw new Error("transakcija odbijena: " + JSON.stringify(s.err));
    if (s && (s.confirmationStatus === "confirmed" || s.confirmationStatus === "finalized")) return true;
    say(el, "Čekam potvrdu mreže… " + (i + 1));
    await new Promise((r) => setTimeout(r, 1500));
  }
  throw new Error("mreža nije potvrdila u 60 s; provjeri na Solscanu");
}

function provider() {
  const p = (window.phantom && window.phantom.solana) || window.solana;
  if (!p || !p.isPhantom) {
    throw new Error("Phantom nije pronađen. Na računalu instaliraj Phantom dodatak; na mobitelu otvori ovu stranicu " +
                    "u Phantomovom pregledniku (ikona 🌐 u Phantomu).");
  }
  return p;
}

function b64(bytes) {
  let s = "";
  bytes.forEach((b) => { s += String.fromCharCode(b); });
  return btoa(s);
}

function unb64(s) {
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}

async function save(pid, mint, status) {
  const body = new URLSearchParams({ mint, status });
  await fetch(`/nas-token/${pid}/adresa`, { method: "POST", body });
}

export async function launchSpl(web3, spl, cfg, el) {
  const net = cfg.net;
  try {
    const p = provider();
    say(el, "Spajam Phantom…");
    const { publicKey } = await p.connect();
    const owner = new web3.PublicKey(publicKey.toString());
    const bh = await rpc(net, "getLatestBlockhash", [{ commitment: "confirmed" }]);
    const mintKp = web3.Keypair.generate();
    const built = buildSplTx(web3, spl, { owner, mintKp, decimals: cfg.decimals, supply: cfg.supply, name: cfg.name,
                                          symbol: cfg.symbol, uri: cfg.uri, blockhash: bh.value.blockhash });
    say(el, "Potvrdi u Phantomu" + (net === "devnet" ? " (Phantom mora biti na Devnetu: Postavke → Developer Settings → Testnet Mode)" : "") + "…");
    const signed = await p.signTransaction(built.tx);
    if (!signed.verifySignatures(false)) throw new Error("potpis nije ispravan");
    const raw = signed.serialize();
    const sig = await rpc(net, "sendTransaction", [b64(raw), { encoding: "base64", preflightCommitment: "confirmed" }]);
    await confirm(net, sig, el);
    await save(cfg.pid, built.mint, net === "devnet" ? "test" : "live");
    el.innerHTML = `✅ Token je napravljen. Adresa: <code>${built.mint}</code> · <a target=_blank rel=noopener ` +
      `href="https://solscan.io/token/${built.mint}${net === "devnet" ? "?cluster=devnet" : ""}">Solscan ↗</a> · ` +
      `<a href="/nas-token/${cfg.pid}">osvježi stranicu</a>`;
  } catch (e) {
    say(el, "Nije prošlo: " + (e && e.message ? e.message : e), true);
  }
}

export async function launchPump(web3, cfg, el) {
  try {
    const p = provider();
    say(el, "Spajam Phantom…");
    const { publicKey } = await p.connect();
    const mintKp = web3.Keypair.generate();
    say(el, "Slažem transakciju za pump.fun…");
    const r = await fetch(`/nas-token/${cfg.pid}/pump-tx`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ publicKey: publicKey.toString(), mint: mintKp.publicKey.toBase58() }) });
    const j = await r.json();
    if (j.error) throw new Error(j.error);
    const tx = web3.VersionedTransaction.deserialize(unb64(j.tx));
    say(el, "Potvrdi u Phantomu (pravi SOL: kreiranje + naša prva kupnja)…");
    const signed = await p.signTransaction(tx);
    signed.sign([mintKp]);
    const sig = await rpc("mainnet", "sendTransaction", [b64(signed.serialize()), { encoding: "base64" }]);
    await confirm("mainnet", sig, el);
    const mint = mintKp.publicKey.toBase58();
    await save(cfg.pid, mint, "live");
    el.innerHTML = `🚀 Lansirano na pump.fun! <a target=_blank rel=noopener href="https://pump.fun/coin/${mint}">` +
      `pump.fun ↗</a> · <a href="/nas-token/${cfg.pid}">osvježi stranicu</a>`;
  } catch (e) {
    say(el, "Nije prošlo: " + (e && e.message ? e.message : e), true);
  }
}
