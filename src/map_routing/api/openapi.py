"""Print the API's OpenAPI description (JSON) to stdout.

`make api-types` feeds it to openapi-typescript, which generates the web app's
TypeScript types (web/src/api/types.ts); no server or data is needed.

    uv run python -m map_routing.api.openapi
"""

import json
from pathlib import Path

from map_routing.api.app import create_app
from map_routing.settings import Settings


def openapi_json() -> str:
    # The description depends only on the code; the data folder is never read.
    app = create_app(Settings(data_dir=Path("data"), user_agent="openapi"))
    return json.dumps(app.openapi(), indent=2, sort_keys=True)


if __name__ == "__main__":
    print(openapi_json())
