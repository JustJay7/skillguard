"""Check only the dedicated host's local listener; never submit a paid action."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


def check(origin_file: Path, *, port: int = 8770) -> None:
    origin = urlsplit(origin_file.read_text().strip())
    if (origin.scheme != 'https' or not origin.hostname or origin.username or origin.password
            or origin.path not in {'', '/'} or origin.query or origin.fragment):
        raise ValueError('Configured HTTPS origin required')
    request = Request(f'http://127.0.0.1:{port}/health', headers={'Host': origin.netloc})
    # Ignore HTTP_PROXY inherited from a shell; this check must remain local.
    with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
        if response.status != 200:
            raise ValueError('Listener unavailable')
        state = json.loads(response.read(4097))
    if (not isinstance(state, dict) or state.get('status') != 'listening'
            or state.get('mode') != 'linux_vm'
            or state.get('depends_on_mac') is not False
            or state.get('authentication_required') is not True):
        raise ValueError('Expected protected dedicated-host listener')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--origin-file', type=Path, required=True)
    args = parser.parse_args()
    try:
        check(args.origin_file)
    except (OSError, ValueError):
        message = 'Dedicated-host listener check failed; inspect private host logs'
        raise SystemExit(message) from None
    print('Protected dedicated-host listener is ready; no model request made')


if __name__ == '__main__':
    main()
