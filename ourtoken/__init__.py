"""Naš token: the players' own Solana meme token, from idea to launch and after.

store.py    nastoken.db: token projects, players' donor wallets, stat snapshots (only the dashboard writes it)
costs.py    what a launch costs on each path (pump.fun, Raydium, Meteora), free vs paid extras
treasury.py the shared vault: reads its PUBLIC address on chain (Helius), who sent what; never holds a key
advisor.py  marketing plan, influencer picks from our KOL data, advice from a live token's numbers

Nothing here signs a transaction or stores a private key: launching and spending from the vault happen in the
players' own wallets (see the decision on the page).
"""
