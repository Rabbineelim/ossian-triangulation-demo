"""Run the Ossian web app:  python -m ossian.web

Deploy-friendly: host/port are read from the environment.
    OSSIAN_HOST (default 127.0.0.1 — use 0.0.0.0 to expose on a network)
    OSSIAN_PORT (default 8000)
"""
import os

import uvicorn

if __name__ == "__main__":
    # Hosts (Render/Railway/Fly/Heroku) inject $PORT; honor it, then OSSIAN_PORT.
    port = int(os.environ.get("PORT") or os.environ.get("OSSIAN_PORT") or "8000")
    uvicorn.run(
        "ossian.web.app:app",
        host=os.environ.get("OSSIAN_HOST", "127.0.0.1"),
        port=port,
        reload=False,
    )
