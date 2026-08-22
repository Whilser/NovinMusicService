import tempfile
import unittest
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class WebApplicationTests(unittest.TestCase):
    def test_spa_and_assets_are_public_without_capturing_api_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            application = create_app(data_dir=Path(directory))
            with TestClient(application) as client:
                index = client.get("/")
                deep_link = client.get("/albums")
                script = client.get("/assets/app.js")
                styles = client.get("/assets/styles.css")
                busy_styles = client.get("/assets/busy.css")
                mobile_styles = client.get("/assets/mobile.css")
                missing_api = client.get("/api/does-not-exist")

            self.assertEqual(index.status_code, 200)
            self.assertIn('id="app"', index.text)
            self.assertEqual(deep_link.status_code, 200)
            self.assertIn('type="module"', deep_link.text)
            self.assertEqual(script.status_code, 200)
            self.assertIn('request("/player/status")', script.text)
            self.assertNotIn(".innerHTML", script.text)
            self.assertEqual(styles.status_code, 200)
            self.assertIn("prefers-reduced-motion", styles.text)
            self.assertEqual(busy_styles.status_code, 200)
            self.assertIn("button-stripes", busy_styles.text)
            self.assertIn("withButtonBusy", script.text)
            self.assertEqual(mobile_styles.status_code, 200)
            self.assertIn("repeat(7", mobile_styles.text)
            self.assertEqual(missing_api.status_code, 404)
            self.assertEqual(missing_api.headers["content-type"], "application/json")

    def test_browser_contract(self):
        completed = subprocess.run(
            ["npm", "run", "test:web"],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("browser smoke:", completed.stdout)


if __name__ == "__main__":
    unittest.main()
