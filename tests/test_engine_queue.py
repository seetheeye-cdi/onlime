from __future__ import annotations

import pytest

from onlime.engine import _RoutingQueue


@pytest.mark.asyncio
async def test_routing_queue_sends_links_to_web_lane():
    queue = _RoutingQueue()

    await queue.put({"content_type": "message"})
    await queue.put({"content_type": "link"})
    await queue.put({"content_type": "voice"})

    assert queue.fast.qsize() == 1
    assert queue.web.qsize() == 1
    assert queue.heavy.qsize() == 1

    assert (await queue.fast.get())["content_type"] == "message"
    assert (await queue.web.get())["content_type"] == "link"
    assert (await queue.heavy.get())["content_type"] == "voice"
