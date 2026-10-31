Site Verdict

ابزار رایگان ممیزی سئو (با بخش اختیاری سئوی محلی) برای وب‌سایت‌ها، با رابط Streamlit و CLI. گزارش به فارسی و انگلیسی.

A free SEO audit tool (with optional local business checks) with a Streamlit dashboard and a command-line interface.
Features / امکانات

    On-page checks: title, meta description, headings, word count, favicon, canonical.
    Images: missing alt text (single source of penalty).
    Links: internal/external, broken links (external status 0 is reported as unverifiable, not broken).
    Technical: TTFB, page size, HTTPS, robots.txt, sitemap.xml.
    Local SEO (optional): NAP, LocalBusiness schema (auto-detected, can be forced with --local / --non-local).
    SSRF-safe HTTP layer: private/loopback targets blocked, IP pinned per request, bounded redirects and body size.

Installation / نصب

python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

Usage / استفاده

Web dashboard:

streamlit run app.py

CLI:

python cli.py https://example.com
python cli.py https://example.com -o report.json
python cli.py https://example.com -f html -o report.html --local

Storage (Python API): audits can be saved to a local SQLite database. The default path is data/site_verdict.db; set SITE_VERDICT_DB to change it.

from seo_core.storage import Storage

storage = Storage()
audit_id = storage.save_audit(report)  # report: AuditReport
storage.list_audits(url="https://example.com")
storage.get_audit(audit_id)

The web app and CLI do not save audits automatically yet.
Tests / تست

pip install -r requirements-dev.txt
python -m pytest -q

Limitations / محدودیت‌ها

    Single-page audit (no full-site crawl yet).
    No JavaScript rendering; no Core Web Vitals or backlink data.
    Respect the target site's terms and robots.txt; use responsibly.

License

MIT License. See LICENSE.