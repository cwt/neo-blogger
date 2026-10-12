"""Promote a named member to administrator and publisher (spec §19.6).

Usage: ``uv run python -m neoblogger.cli.admin_repair <display_name> [config_path]``

The startup backfill only promotes a *lone* member; a multi-member
database with no administrator needs this explicit repair instead of a
silent guess (tech-req §5.7).
"""

import asyncio
import sys

from ..app.config import load_config
from ..app.context import AppContext


async def run(display_name: str, config_path: str | None = None) -> bool:
    context = AppContext.build(load_config(config_path))
    try:
        await context.database.start()
        member = await context.members.by_display_name(display_name)
        if member is None:
            print(f"No member named {display_name!r}.", file=sys.stderr)
            return False
        await context.members.promote_admin(member["_id"])
        member["administrator"] = True
        member["publisher"] = True
        await context.visibility.resync_author_articles(member)
        await context.meta.bump_content_version()
        print(f"Promoted {display_name!r} to administrator and publisher.")
        return True
    finally:
        await context.close()


def main() -> None:
    if len(sys.argv) not in (2, 3):
        print(
            "usage: python -m neoblogger.cli.admin_repair <display_name> [config_path]",
            file=sys.stderr,
        )
        sys.exit(2)
    config_path = sys.argv[2] if len(sys.argv) == 3 else None
    if not asyncio.run(run(sys.argv[1], config_path)):
        sys.exit(1)


if __name__ == "__main__":
    main()
