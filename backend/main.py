import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from routers import odds, opportunities

load_dotenv()
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="MasG EV Tool API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(odds.router, prefix="/api")
app.include_router(opportunities.router, prefix="/api")
