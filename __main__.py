"""`python -m alibi`: serve the API with uvicorn (ALIBI_HOST, ALIBI_PORT; default 127.0.0.1:8601)."""

import os

import uvicorn


def main() -> None:
    uvicorn.run("alibi.api:app", host=os.environ.get("ALIBI_HOST", "127.0.0.1"),
                port=int(os.environ.get("ALIBI_PORT", "8601")), log_level="info")


if __name__ == "__main__":
    main()
