from typing import AsyncGenerator
import os
import ssl
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv(override=True)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://avnadmin:<redacted>@pg-3d4feff9-davfran9090-88a1.c.aivencloud.com:11427/defaultdb?sslmode=require",
)

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgres+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgres+asyncpg://", "postgresql+asyncpg://", 1)

connect_args = {}
parts = urlsplit(DATABASE_URL)
query = dict(parse_qsl(parts.query, keep_blank_values=True))
sslmode = query.pop("sslmode", None)

if (sslmode and sslmode != "disable") or (parts.hostname or "").endswith(".aivencloud.com"):
    ca_cert_path = os.getenv("PGSSLROOTCERT") or os.getenv("AIVEN_CA_CERT_PATH")
    if ca_cert_path:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.load_verify_locations(cafile=ca_cert_path)
        connect_args["ssl"] = ssl_context
    else:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ssl_context
    DATABASE_URL = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

engine: AsyncEngine = create_async_engine(DATABASE_URL, echo=False, connect_args=connect_args)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
