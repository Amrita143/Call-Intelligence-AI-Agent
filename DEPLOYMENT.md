# Deployment guide

The whole app is **one FastAPI service** that serves both the API and the frontend, so
you deploy a single service — no separate frontend host. It's containerized
(`Dockerfile`) and binds to `$PORT`, so it drops straight onto any free container host.

**Recommended (easiest, free, handles streaming): [Render](#option-a--render-recommended).**
Also covered: [Hugging Face Spaces](#option-b--hugging-face-spaces-docker) and
[Railway](#option-c--railway). A note on [why not Vercel](#a-note-on-vercel) is at the end.

---

## 0. Before you deploy (do this once)

### a) Rotate and protect your keys
The keys currently in `.env` were shared in development. **Rotate them** and never commit
`.env` to a public repo:
- OpenAI → https://platform.openai.com/api-keys (create a new key, revoke the old)
- AssemblyAI → https://www.assemblyai.com/app (regenerate)
- Supabase service role → Project → Settings → API (roll if exposed)

Make sure `.env` is git-ignored:
```bash
echo ".env" >> .gitignore
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

### c) The environment variables every host needs
Set these in the host's dashboard (NOT in the repo):

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

## Option A — Render (recommended)

Free, no card required, supports Docker and long-lived SSE streams.

1. Go to **https://render.com** → sign in with GitHub.
2. **New +** → **Web Service** → connect your repo.
3. Render auto-detects the `Dockerfile`. Set:
   - **Name:** `call-intelligence-agent`
   - **Instance Type:** **Free**
   - **Region:** any
   - (Render provides `$PORT` automatically; the Dockerfile already uses it.)
4. Open **Environment** → **Add Environment Variable** and paste the variables from
   [step 0c](#c-the-environment-variables-every-host-needs).
5. **Create Web Service**. First build takes ~3–5 min. You'll get a URL like
   `https://call-intelligence-agent.onrender.com`.
6. Open the URL, load a sample, click **Analyze call**. Done.

**Prefer no Docker?** Render can run it natively:
- Runtime **Python 3**, **Build Command:** `pip install -r backend/requirements.txt`,
  **Start Command:** `uvicorn server:app --app-dir backend --host 0.0.0.0 --port $PORT`.

> Free instances sleep after ~15 min idle and cold-start in ~30–60 s on the next request —
> fine for a demo. Mention this to reviewers so the first click isn't a surprise.

---

## Option B — Hugging Face Spaces (Docker)

Also free and very quick; great for a shareable demo link.

1. https://huggingface.co/new-space → **Space SDK: Docker** → **Blank**.
2. Push this repo into the Space (or connect the GitHub repo).
3. In the Space, edit the top of `README.md` to add HF metadata and the app port:
   ```yaml
   ---
   title: Call Intelligence Agent
   sdk: docker
   app_port: 7860
   ---
   ```
4. **Settings → Variables and secrets** → add the keys from
   [step 0c](#c-the-environment-variables-every-host-needs), **plus** `PORT=7860`
   (HF serves on 7860; the Dockerfile honors `$PORT`).
5. The Space builds and serves at `https://<user>-call-intelligence-agent.hf.space`.

---

## Option C — Railway

1. https://railway.app → **New Project** → **Deploy from GitHub repo**.
2. Railway detects the `Dockerfile` and builds it.
3. **Variables** → add the keys from [step 0c](#c-the-environment-variables-every-host-needs)
   (Railway injects `$PORT` automatically).
4. **Settings → Networking → Generate Domain** to get a public URL.

> Railway's free tier runs on trial credits; fine for short-lived demos.

---

## A note on Vercel

Vercel is excellent for static sites and short serverless functions, but it's a poor fit
for **this** app: the analysis endpoint holds an open **Server-Sent Events** stream and does
several seconds of LLM work (and AssemblyAI polling for audio), which exceeds Vercel's
serverless function model and Hobby timeouts. You'd have to restructure the streaming
pipeline into background jobs.

**Use a container host (Render / Railway / HF Spaces) instead** — the app is a long-lived
streaming server and runs there unchanged. If you specifically need Vercel, host only a
static frontend there and point it at the FastAPI backend deployed on Render.

---

## Post-deploy checklist

- [ ] Home page loads; the header chips show your LLM model, Supabase, and Audio status.
- [ ] Loading a sample → **Analyze call** streams the trace and renders results.
- [ ] **History** tab lists the run (confirms Supabase writes work from the host).
- [ ] Audio upload transcribes (if `ASSEMBLYAI_API_KEY` is set).
- [ ] With keys removed, the app still loads in mock mode (good fallback for reviewers).
