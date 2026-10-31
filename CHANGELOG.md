Changelog

All notable changes to this project are documented here.
The format follows Keep a Changelog.
[0.3.0] - 2026-10-31
Added

    SQLite storage layer (seo_core/storage.py): Storage class with save_audit, list_audits (optional URL filter, newest first), and get_audit. Database defaults to data/site_verdict.db, overridable with the SITE_VERDICT_DB environment variable. Schema versioning is included.

[0.2.0] - 2026-10-29
Changed

    Audits run through an explicit stage pipeline (seo_core/pipeline.py, seo_core/stages.py); analyzer calls go through seo_core/invoke.py.
    Duplicated analyzer-call helpers removed from seo_core/engine.py.
    CLI entry point renamed to site-verdict (reinstall the package to update).
    CI runs on ubuntu-24.04 instead of ubuntu-latest.

Fixed

    Persian words joined by a zero-width non-joiner (e.g. می‌خواهم) are counted as one word instead of being split.

[0.1.0] - 2026-10-28
Added

    Local SEO analysis with auto-detection and manual override (--local / --non-local).
    CLI JSON and HTML report output (-o report.json|report.html) and printed issue/warning lists.
    Unverifiable link category for external links that return status 0 (not counted as broken).
    Shared SSRF-safe HTTP layer (seo_core/safe_http.py): IP pinning per request, bounded redirects and body size, public-API transport.
    Deterministic link candidate selection.
    Analyzer failure handling: each failed analyzer costs 10 points, and the score is capped at 70 when any analyzer fails.
    Local regression tests for CLI, SSRF, analyzers, engine, reporters, and formatting.

Changed

    Missing alt text is penalized only by the images analyzer (previously penalized twice).
    Local SEO penalties apply only when local business mode is on.
    Local SEO analyzers run in a thread, and synchronous HTML parsing no longer blocks the event loop.
    Link checks use 15 concurrent requests (was 10).
    Persian word counting excludes Arabic-Indic digits and tatweel.
    Digit formatting for display is unified (stored data is unchanged).
    Dependencies cleaned up: duplicate brotli removed; unused Persian text packages removed.
    get_val moved to seo_core/access.py.
    Test helpers no longer use exec; CLI tests are independent of the working directory.

Fixed

    External links with status 0 were reported as broken.
