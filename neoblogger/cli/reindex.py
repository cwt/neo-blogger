"""Rebuild all full-text search indexes (spec §11.4) against the configured DB.

Usage: ``uv run python -m neoblogger.cli.reindex``
Required after switching tokenizers, because existing index entries must
be regenerated under the new segmentation rules (§12.2).
"""

import asyncio

from ..app.config import load_config
from ..app.context import AppContext
from ..app.repositories.articles import ArticleRepository


async def run(config_path: str | None = None) -> None:
    context = AppContext.build(load_config(config_path))
    try:
        await context.database.start()
        await ArticleRepository(context.database).rebuild_search_indexes()
        print("Search indexes rebuilt.")
    finally:
        await context.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
