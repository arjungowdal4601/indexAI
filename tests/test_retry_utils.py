import tempfile
import unittest

from unittest.mock import patch

from backend.services import job_event_service
from backend.services.retry_utils import is_transient_error, run_with_retries


class RetryUtilsTests(unittest.TestCase):
    def test_run_with_retries_retries_transient_errors_and_calls_hooks(self):
        attempts = []
        retry_events = []
        wait_events = []

        def flaky_operation():
            attempts.append("call")
            if len(attempts) < 3:
                raise RuntimeError("Connection timeout 503")
            return "ok"

        result = run_with_retries(
            flaky_operation,
            max_attempts=3,
            initial_delay_seconds=0,
            on_retry=lambda attempt, exc: retry_events.append((attempt, type(exc).__name__)),
            on_wait=lambda attempt, delay, exc: wait_events.append((attempt, delay)),
        )

        self.assertEqual(result, "ok")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(retry_events, [(1, "RuntimeError"), (2, "RuntimeError")])
        self.assertEqual(wait_events, [(1, 0), (2, 0)])

    def test_run_with_retries_does_not_retry_non_transient_errors(self):
        calls = []

        def broken_operation():
            calls.append("call")
            raise ValueError("schema is invalid")

        with self.assertRaises(ValueError):
            run_with_retries(broken_operation, max_attempts=3, initial_delay_seconds=0)

        self.assertEqual(calls, ["call"])
        self.assertFalse(is_transient_error(ValueError("schema is invalid")))

    def test_job_event_waiting_and_retry_helpers_write_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job_id = "job_000001"
            with patch.dict("os.environ", {"INDEXAI_STORAGE_ROOT": temp_dir}):
                job_event_service.append_waiting_for_llm(
                    job_id,
                    stage="document_indexing",
                    step="waiting_for_llm",
                    message="Waiting for LLM response for indexing page 1",
                    progress_current=1,
                    progress_total=3,
                )
                job_event_service.append_retry(
                    job_id,
                    stage="document_indexing",
                    step="retry",
                    attempt=1,
                    error=RuntimeError("Connection timeout"),
                    progress_current=1,
                    progress_total=3,
                )

                events = job_event_service.read_events(job_id).events

        self.assertEqual([event.step for event in events], ["waiting_for_llm", "retry"])
        self.assertIn("Waiting for LLM response", events[0].message)
        self.assertIn("Retry attempt 1", events[1].message)


if __name__ == "__main__":
    unittest.main()
