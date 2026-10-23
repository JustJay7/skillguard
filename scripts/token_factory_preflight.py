"""Read account capabilities without inference calls or compute creation.

Requires python-dotenv, requests, and contree-client[httpx]==0.2.1.
"""

import json
import os
from pathlib import Path

import requests
from contree_client.exceptions import ContreeAPIError
from contree_client.httpx import ContreeClient
from contree_client.runtime import RetryPolicy
from dotenv import load_dotenv


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    key = os.environ.get("NEBIUS_API_KEY", "").strip()
    if not key:
        raise SystemExit("NEBIUS_API_KEY is missing; no request sent")
    output = Path("results")
    output.mkdir(exist_ok=True)
    response = requests.get(
        "https://api.tokenfactory.nebius.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=30,
        allow_redirects=False,
    )
    if response.status_code != 200:
        raise SystemExit(f"Model catalog HTTP {response.status_code}; body withheld")
    catalog = response.json()
    (output / "token_factory_models.json").write_text(json.dumps(catalog, indent=2) + "\n")
    print("Model catalog entries:", len(catalog["data"]))
    project = os.environ.get("NEBIUS_AI_PROJECT", "").strip()
    result = {"status": "project_required", "spawn_verified": False}
    if project:
        try:
            with ContreeClient(
                key,
                project=project,
                base_url="https://api.tokenfactory.nebius.com/sandboxes",
                timeout=30,
                retry=RetryPolicy(max_attempts=1),
            ) as client:
                client.list_images(limit=1)
            result["status"] = "read_access_confirmed"
        except ContreeAPIError as error:
            result.update(status="access_check_failed", http_status=error.status)
        except Exception as error:
            result.update(status="client_or_transport_failure", exception_type=type(error).__name__)
    (output / "token_factory_sandbox_access.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
