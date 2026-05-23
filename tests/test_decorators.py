import pytest

from src.sdk.decorators import task


class TestTaskDecorator:
    def test_task_metadata_is_attached_to_returned_wrapper(self):
        class ExampleAgent:
            @task(name="sync-record", retries=3, timeout=7)
            async def sync(self):
                return "ok"

        metadata = ExampleAgent.sync.__task_config__

        assert metadata == {
            "name": "sync-record",
            "retries": 3,
            "timeout": 7,
        }

    @pytest.mark.asyncio
    async def test_task_wrapper_still_calls_original_function(self):
        class ExampleAgent:
            @task(timeout=7)
            async def sync(self):
                return "ok"

        assert await ExampleAgent().sync() == "ok"
