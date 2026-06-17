from fastapi import FastAPI

from runner_app.routes import router

app = FastAPI(title="PBN Python Runner")
app.include_router(router)
