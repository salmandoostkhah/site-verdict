Site Verdict

ابزار رایگان ممیزی سئو و سئوی محلی برای وب‌سایت‌ها، با رابط Streamlit و CLI. گزارش به فارسی و انگلیسی.

A free SEO and local SEO audit tool with a Streamlit dashboard and a command-line interface.
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

Tests / تست

pip install -r requirements-dev.txt
python -m pytest -q

Limitations / محدودیت‌ها

    Single-page audit (no full-site crawl yet).
    No JavaScript rendering; no Core Web Vitals or backlink data.
    Respect the target site's terms and robots.txt; use responsibly.

License

MIT License. See LICENSE.