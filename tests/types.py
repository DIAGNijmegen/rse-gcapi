import asyncio

from gcapi import AsyncClient, Client

client = Client()

page = client.algorithms.page()
reveal_type(page)  # "gcapi.apibase.PageResult[gcapi.models.Algorithm]"

item = next(client.algorithms.iterate_all())
reveal_type(item)  # "gcapi.models.Algorithm"


el = asyncio.new_event_loop()


async def f() -> None:
    aclient = AsyncClient()

    page = await aclient.algorithms.page()
    reveal_type(page)  # "gcapi.apibase.PageResult[gcapi.models.Algorithm]"

    item = await anext(aclient.algorithms.iterate_all())
    reveal_type(item)  # "gcapi.models.Algorithm"


el.run_until_complete(f())
