# MemeSonar MCP server (za Groka)

> **Najjednostavnije (ništa se ne instalira):** aplikacija sama poslužuje MCP na `https://app.memesonar.app/mcp`.
> Na Autopilot stranici pod „Još → Grok (MCP)” tapni **Napravi MCP ključ**, pa **Kopiraj ključ**. U Groku upiši tu
> adresu i zaglavlje `Authorization: Bearer <ključ>`. Ova mapa (`mcp_server/`) treba samo ako želiš server pokretati
> na svom računalu.

Grok (ili bilo koji MCP klijent) preko ovog servera čita podatke MemeSonara uživo i može **zatražiti** trgovinu.

| Alat | Što radi |
|---|---|
| `get_market_signals` | Što se sada zove na Solani (X, Telegram, praćeni novčanici). Za svaki token: tko ga je zvao, cijena, MC, likvidnost, volumen, promjena 5m/1h/24h i udio kupnji u zadnjem satu. |
| `get_token_details` | Jedan token po adresi: tržište uživo, tko ga je zvao u zadnjem satu, naša otvorena pozicija u njemu. |
| `get_portfolio_status` | Autopilot: način rada (live, probno, isključen), vrijednost walleta, limiti, otvorene pozicije s PnL-om, otvoreni nalozi. |
| `execute_trade` | **Ne trguje sam.** Zahtjev ide u red „Zahtjevi s Groka” na Autopilot stranici. Izvršava se tek kad vlasnik tapne **Odobri** (vrijedi 15 min). `require_approval` mora biti `true`. |

Server ne drži nijednu bazu ni ključ walleta. Sve podatke pita aplikaciju MemeSonar (`/api/mcp/*`) s posebnim ključem.

## 1. Ključ u aplikaciji (jednom)

Na Renderu dodaj varijablu (https://dashboard.render.com/web/srv-dbih7tm1egvs73erog0g/env):

- **Key:** `MCP_API_KEY`
- **Value:** dugačak nasumični niz. Na računalu ga napraviš s `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

Zatim klikni **Save, rebuild, and deploy**. Dok ta varijabla ne postoji, `/api/mcp/*` odgovara 404.

## 2. Pokretanje na računalu

```bash
cd mcp_server
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export MEMESONAR_API_KEY="<isti niz kao MCP_API_KEY na Renderu>"
export MCP_SERVER_KEY="<drugi nasumični niz: ovaj ključ upisuješ u Groka>"
# Windows (PowerShell): $env:MEMESONAR_API_KEY="..." ; $env:MCP_SERVER_KEY="..."

python main.py
```

Server sluša na `http://0.0.0.0:3001/mcp`. Svaki zahtjev mora imati zaglavlje `Authorization: Bearer <MCP_SERVER_KEY>`, inače dobiva 401.

## 3. ngrok tunel (da Grok dođe do servera)

1. Napravi račun na https://dashboard.ngrok.com i instaliraj ngrok.
2. Jednom upiši svoj token: `ngrok config add-authtoken <tvoj ngrok token>`.
3. Dok `main.py` radi, u drugom prozoru pokreni: `ngrok http 3001`.
4. ngrok ispiše adresu, npr. `https://abcd-1234.ngrok-free.app`. MCP adresa je ta adresa plus `/mcp`:
   `https://abcd-1234.ngrok-free.app/mcp`

Besplatni ngrok mijenja adresu pri svakom pokretanju, pa je tada treba ponovno upisati u Groka. Stalnu adresu daje ngrok plaćeni plan (static domain).

## 4. U Groku

Dodaj MCP server (remote / Streamable HTTP):

- **URL:** `https://<tvoja-ngrok-adresa>/mcp`
- **Zaglavlje:** `Authorization: Bearer <MCP_SERVER_KEY>`

## Sigurnost

- Ključeve nikad ne lijepi u chat, na GitHub ni u objave. Drži ih samo u varijablama okoline.
- `execute_trade` uvijek čeka tvoje „Odobri”. Grok čita javne postove, a lažni post ga može navesti da zatraži trgovinu.
- Kad ne koristiš Groka, ugasi `main.py` i ngrok. Za potpuno gašenje obriši `MCP_API_KEY` na Renderu.
