from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

EXPO_WEB_ORIGIN = "http://localhost:8081"

app = FastAPI(title="Expo FastAPI Todo API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[EXPO_WEB_ORIGIN],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=[],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
