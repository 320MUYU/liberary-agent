from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.models.users import User
from app.database import Base, create_database_if_not_exists, engine
from app.api import api

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_database_if_not_exists()
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(api)

@app.get("/")
def root():
    return {"message": "FastAPI正在运行中"}
