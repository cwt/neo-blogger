"""Print a strong random secret key for ``[application] secret_key`` (§15.9).

Usage: ``uv run python -m neoblogger.cli.secret``
"""

import secrets


def main() -> None:
    print(secrets.token_urlsafe(32))


if __name__ == "__main__":
    main()
