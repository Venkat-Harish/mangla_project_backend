"""Azure Functions entry point: one HTTP function hands every request to the FastAPI app.

The routes, validation and error responses are app/main.py's; host.json sets an empty route
prefix, so the URLs are the same as under uvicorn (/app/...). Deployment: docs/Deployment.md.
"""

import azure.functions as func

from app.main import app as fastapi_app

app = func.AsgiFunctionApp(app=fastapi_app, http_auth_level=func.AuthLevel.ANONYMOUS)
