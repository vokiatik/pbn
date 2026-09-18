from dataclasses import replace
from threading import Event
from unittest.mock import Mock, patch

from worker_app.config import load_config
from worker_app.redis_worker import start_workers, worker_loop


def test_shutdown_finishes_popped_job_before_exiting():
    stopping = Event()
    redis = Mock()
    # A signal can arrive while BLPOP is waiting. An already removed job must
    # finish; dropping it here would permanently lose it from this queue.
    def pop(*_args, **_kwargs):
        stopping.set()
        return ("pbn:jobs", '{"type":"generate_ai_image","project_id":"test"}')
    redis.blpop.side_effect = pop
    runner = Mock()
    runner.is_ready.return_value = True
    processor = Mock()
    with patch("worker_app.redis_worker.create_redis_client", return_value=redis), \
         patch("worker_app.redis_worker.PythonRunnerClient", return_value=runner), \
         patch("worker_app.redis_worker.JobProcessor", return_value=processor):
        worker_loop("test", load_config(), stopping)
    processor.process.assert_called_once_with({"type": "generate_ai_image", "project_id": "test"})
    redis.blpop.assert_called_once()
    redis.close.assert_called_once()


def test_shutdown_does_not_pop_another_job():
    stopping = Event()
    stopping.set()
    redis = Mock()
    with patch("worker_app.redis_worker.create_redis_client", return_value=redis):
        worker_loop("test", load_config(), stopping)
    redis.blpop.assert_not_called()
    redis.close.assert_called_once()


def test_zero_workers_fails_startup():
    try:
        start_workers(replace(load_config(), concurrency=0))
    except ValueError:
        return
    raise AssertionError("zero workers must fail startup")
