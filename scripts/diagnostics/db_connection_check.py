import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.env_files import resolve_env_file

# Load canonical runtime env
BASE_DIR = REPO_ROOT / "server"
env_path = resolve_env_file(REPO_ROOT, BASE_DIR)
if env_path.exists():
    load_dotenv(env_path)


def check_connections() -> None:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ.get("POSTGRES_DB")
    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")

    dsn = f"host={host} port={port} dbname={dbname} user={user} password={password}"

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        count(*), 
                        application_name, 
                        state, 
                        query 
                    FROM pg_stat_activity 
                    WHERE datname = %s
                    GROUP BY application_name, state, query
                    ORDER BY count DESC;
                """,
                    (dbname,),
                )

                rows = cur.fetchall()
                print(f"{'Count':<5} | {'App Name':<20} | {'State':<15} | {'Last Query'}")
                print("-" * 80)
                for count, app, state, query in rows:
                    query_snippet = (query[:50] + "...") if query and len(query) > 50 else query
                    print(f"{count:<5} | {str(app):<20} | {str(state):<15} | {query_snippet}")
    except Exception as e:
        print(f"Error connecting to DB: {e}")


if __name__ == "__main__":
    check_connections()
