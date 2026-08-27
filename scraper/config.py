from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    host: str = os.getenv("POSTGRES_HOST")
    port: int = int(os.getenv("POSTGRES_PORT"))
    database: str = os.getenv("POSTGRES_DB")
    user: str = os.getenv("POSTGRES_USER")
    password: str = os.getenv("POSTGRES_PASSWORD")

config = Config()