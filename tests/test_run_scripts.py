import unittest
from pathlib import Path


class RunScriptTests(unittest.TestCase):
    def test_indexai_runner_uses_compute_conda_env_for_backend_and_frontend(self):
        script = Path("run_indexai_app.ps1")
        old_script = Path("run_comparison_app.ps1")

        self.assertTrue(script.exists())
        self.assertFalse(old_script.exists())
        text = script.read_text(encoding="utf-8")

        self.assertIn('Default: "compute"', text)
        self.assertIn("conda run -n $CondaEnv", text)
        self.assertIn("uvicorn backend.app:app", text)
        self.assertIn("streamlit run frontend/streamlit_app.py", text)
        self.assertIn("python -m pip install -r", text)
        self.assertIn("multipart", text)
        self.assertIn("PYTHONPATH", text)
        self.assertIn("INDEXAI_API_BASE_URL", text)
        self.assertIn("Starting IndexAI app", text)
        self.assertIn("Start-Job", text)
        self.assertIn("Receive-Job -Job $job -ErrorAction Continue", text)
        self.assertIn('"Failed", "Stopped", "Completed"', text)
        self.assertIn("Stop-Job", text)
        self.assertNotIn("comparison", text.lower())


if __name__ == "__main__":
    unittest.main()
