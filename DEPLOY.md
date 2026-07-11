# Deploying Ossian (permanent public link)

You need a host account (free tiers exist). Pick **one** path below. All of them
give you a permanent `https://…` link that works without your PC being on.

---

## Option A — Render.com (easiest, free, no card)

1. Put this project on GitHub:
   ```bash
   cd "Ossian"
   git init && git add . && git commit -m "Ossian Steps 2-3"
   # create an empty repo on github.com, then:
   git remote add origin https://github.com/<you>/ossian.git
   git push -u origin main
   ```
   (`.dockerignore` / `.gitignore` keep the big `data/` and `storage/` out.)
2. Go to **render.com → New + → Blueprint**, choose your repo. Render reads
   `render.yaml` and builds it. In ~3 minutes you get a link like
   `https://ossian.onrender.com`.

Free instances sleep after ~15 min idle and wake on the next request (a few
seconds), and the disk resets on redeploy — fine for a demo. For permanent data,
add a persistent disk and set `OSSIAN_STORAGE=/var/data`.

## Option B — Railway.app
New Project → Deploy from GitHub repo. Railway auto-detects the `Procfile`.
Set no env vars; it injects `$PORT`. Gives `https://<app>.up.railway.app`.

## Option C — Fly.io (Docker, always-on)
```bash
fly launch --dockerfile Dockerfile   # follow prompts, pick a region
fly deploy
```
Gives `https://<app>.fly.dev`. Add a volume for persistent storage:
`fly volumes create data --size 1` and mount at `/app/storage`.

## Option D — any Docker host / your own VPS
```bash
docker build -t ossian .
docker run -p 8000:8000 -v ossian_data:/app/storage ossian
```

---

## Things to know before you share the link

- **No login yet.** Anyone with the link can create/delete projects and upload
  files. Add authentication before sharing publicly with real customer data.
  (A simple option: put it behind Cloudflare Access, or add HTTP basic-auth
  middleware — ask and I'll wire it in.)
- **Legacy `.doc` on a Linux host** falls back to the `olefile` reader (Microsoft
  Word isn't available there). `.docx`, PDF, CSV, XLSX, TXT, VTT all work fully.
- **"Load sample datasets"** only works if the `data/` folder is present. It's
  excluded from deploys on purpose (too large); customers upload their own files.
- **Storage** on free tiers is ephemeral. Mount a volume (see each option) to
  keep projects across restarts.

## Temporary link right now (no host needed)
While your PC + app are running, expose it with Cloudflare Tunnel:
```bash
cloudflared tunnel --url http://localhost:8000
```
It prints a `https://<random>.trycloudflare.com` link. Dies when you stop it.
