"""CLI: python -m jobs.seed [샘플 디렉터리]"""

import asyncio
import sys
from pathlib import Path

from app.db import dispose_engine, get_sessionmaker
from jobs.seed import SAMPLES_DIR, run


async def main() -> None:
    samples_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else SAMPLES_DIR
    try:
        result = await run(get_sessionmaker(), samples_dir)
    finally:
        await dispose_engine()
    print("시드 완료:", ", ".join(f"{k}={v}" for k, v in result.items()))


if __name__ == "__main__":
    asyncio.run(main())
