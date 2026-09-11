import asyncpg
from app.config import Config
#global pool variable to hold the connection pool instance
_pool: asyncpg.Pool | None = None

"""why we create the pool is to manage a set of database connections that can be reused across multiple requests or operations.
This is important for performance and resource management, 
as establishing a new database connection for each request can be time-consuming and resource-intensive. 
By using a connection pool, we can reduce the overhead of creating and closing connections, 
and we can also limit the number of concurrent connections to the database, which can help prevent overloading the database server.
"""

async def init_pool(config: Config) -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        config.database_url,
        min_size=config.db_pool_min,
        max_size=config.db_pool_max,
    )


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized")
    return _pool