"""Explicit local same-origin authored-mock host. Importing opens no resource."""

import json

from .api.http import create_app
from .api.security import SessionGuard
from .runtime.local import local_host


def serve_command(arguments):
    import uvicorn

    origin = f"http://127.0.0.1:{arguments.port}"
    host = local_host(arguments.database, arguments.call_database, arguments.namespace)
    app = create_app(host, SessionGuard(origin), assets=arguments.assets)
    print(
        json.dumps(
            {
                "url": origin,
                "execution_origin": "authored_synthetic_mock",
                "live_model_calls": False,
                "public_authentication": False,
            }
        ),
        flush=True,
    )
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=arguments.port,
        access_log=False,
        proxy_headers=False,
        server_header=False,
        log_level="warning",
    )
    return 0
