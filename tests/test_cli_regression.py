"""
CLI regression tests — verify that cli.py runs without AttributeError
for valid and invalid inputs.
"""
import subprocess
import sys
from pathlib import Path
import pytest


ROOT = Path(__file__).resolve().parent.parent
CLI = [sys.executable, str(ROOT / "cli.py")]


class TestCLIBasicInvocation:
    def test_no_args_exits_nonzero(self):
        r = subprocess.run(CLI, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
        assert r.returncode != 0

    def test_help_flag(self):
        r = subprocess.run(CLI + ["--help"], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
        assert r.returncode == 0
        assert "url" in r.stdout.lower() or "usage" in r.stdout.lower()


class TestCLIPrivateURLBlocked:
    @pytest.mark.parametrize("url", [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://192.168.1.1/",
    ])
    def test_private_url_exits_nonzero(self, url):
        r = subprocess.run(CLI + [url], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT, timeout=60)
        assert r.returncode != 0
        # Must not be an AttributeError crash
        assert "AttributeError" not in r.stderr


class TestCLIOutputFormat:
    def test_valid_url_no_attribute_error(self, monkeypatch, capsys):
        """
        Network failure must produce a clean exit 1 with a message, never a
        traceback. Runs in-process with the audit mocked (no real network),
        so it is not affected by DNS or external site latency.
        """
        import cli
        from seo_core.engine import AuditEngine

        async def _offline(self):
            raise OSError("network unreachable (mocked)")

        monkeypatch.setattr(AuditEngine, "audit", _offline)
        with pytest.raises(SystemExit) as exc:
            cli.run_cli("https://example.com")
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "Audit failed" in out
        assert "AttributeError" not in out