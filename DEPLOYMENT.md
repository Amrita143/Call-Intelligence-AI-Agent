# Deployment guide (Railway)

The whole app is **one FastAPI service** that serves both the API and the frontend, so
you deploy a single service — no separate frontend host. It's containerized
(`Dockerfile`) and binds to `$PORT`, so it drops straight onto Railway's free tier.

---

## 0. Before you deploy (do this once)

### a) Rotate and protect your keys
The keys currently in `.env` were shared in development. **Rotate them** and never commit
`.env` to a public repo:
- OpenAI → https://platform.openai.com/api-keys (create a new key, revoke the old)
- AssemblyAI → https://www.assemblyai.com/app (regenerate)
- Supabase service role → Project → Settings → API (roll if exposed)

Make sure `.env` is git-ignored (the repo's `.gitignore` already lists it):
```bash
git check-ignore .env    # should print ".env"
```

### b) Push the code to GitHub
```bash
cd "Call Intelligence Agent"
git init
git add .
git commit -m "Call Intelligence Agent"
git branch -M main
git remote add origin https://github.com/<you>/call-intelligence-agent.git
git push -u origin main
```

### c) The environment variables Railway needs
Set these in Railway's **Variables** tab (NOT in the repo):

| Variable | Required? | Value |
|---|---|---|
| `OPENAI_API_KEY` | for real LLM output | your OpenAI key (omit → runs in mock mode) |
| `MODEL` | optional | `gpt-4.1` |
| `ASSEMBLYAI_API_KEY` | for audio upload | your AssemblyAI key (omit → audio disabled) |
| `SUPABASE_URL` | for history/domains | `https://<ref>.supabase.co` |
| `SUPABASE_SERVICE_ROLE_SECRET` | for history/domains | Supabase service role key |
| `SUPABASE_PUBLIC_ANON_KEY` | optional fallback | Supabase anon key |

> With **no keys at all** the app still boots and runs in deterministic **mock mode** — handy
> for a zero-cost public demo. Add keys later to enable live LLM / audio / persistence.

### d) Supabase tables
The bundled project already has them. If you point at **your own** Supabase project, open
its SQL Editor and run [`backend/schema.sql`](backend/schema.sql) once to create the
`runs` and `domains` tables.

---

## 1. Deploy on Railway

1. Go to **https://railway.app** → sign in with GitHub.
2. **New Project** → **Deploy from GitHub repo** → pick your repo.
3. Railway detects the `Dockerfile` and starts building automatically.
   (Railway injects `$PORT`; the Dockerfile already uses it — nothing to configure.)
4. Open the service → **Variables** → add the keys from
   [step 0c](#c-the-environment-variables-railway-needs) → the service redeploys.
5. **Settings → Networking → Generate Domain** to get a public URL, e.g.
   `https://call-intelligence-agent-production.up.railway.app`.
6. Open the URL, load a sample, click **Analyze call**. Done.

> Railway's free tier runs on monthly trial credits and sleeps when idle — fine for a demo.
> Tell reviewers the first request after idle may take a few seconds to wake.

---

## Post-deploy checklist

- [ ] Home page loads; the header chips show your LLM model, Supabase, and Audio status.
- [ ] Loading a sample → **Analyze call** streams the trace and renders results.
- [ ] **History** tab lists the run (confirms Supabase writes work from the host).
- [ ] Audio upload transcribes (if `ASSEMBLYAI_API_KEY` is set).
- [ ] With keys removed, the app still loads in mock mode (good fallback for reviewers).
