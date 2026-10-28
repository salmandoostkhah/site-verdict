import json
import sys
from pathlib import Path

# اجازه ایمپورت ماژول‌های ریشه پروژه (cli, seo_core) وقتی از tools/ اجرا می‌شود
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cli
from seo_core.models import AuditReport

class FakeEngine:
    def __init__(self, url, local_business=None):
        self.url = url
        self.local_business = local_business

    async def audit(self):
        return AuditReport(
            url=self.url,
            score=81,
            issues=["Missing meta description"],
            recommendations=["Add alt text"],
        )

cli.AuditEngine = FakeEngine

OUT = Path(__file__).resolve().parent
cli.main(["https://example.com", "-o", str(OUT / "test_out.json")])
cli.main(["https://example.com", "-o", str(OUT / "test_out.html")])

print("JSON score:", json.load(open(OUT / "test_out.json", encoding="utf-8"))["score"])
print("HTML ok:", open(OUT / "test_out.html", encoding="utf-8").read().startswith("<!DOCTYPE"))