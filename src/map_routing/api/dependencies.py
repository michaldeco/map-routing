"""Objects the endpoints receive from FastAPI (dependency injection).

The endpoints live in router modules (`areas.py`, `scenarios.py`, ...), outside
`create_app`, so they cannot see the store as a variable. `create_app` puts it on
`app.state`; an endpoint declares `store: Store` and FastAPI passes it in through
`get_store`. Tests get their own store by calling `create_app(settings)`.
"""

from typing import Annotated

from fastapi import Depends, Request

from map_routing.api.data import DataStore


def get_store(request: Request) -> DataStore:
    return request.app.state.store


Store = Annotated[DataStore, Depends(get_store)]
