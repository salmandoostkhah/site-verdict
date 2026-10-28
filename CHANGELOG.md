Changelog

All notable changes to this project are documented here.
The format follows Keep a Changelog.
[0.1.0] - Unreleased
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
    Duplicate penalties for missing alt text.
    Flaky test on attribute errors (isolated).
    .elapsed RuntimeError when the response was not closed.
    transport._pool coupling replaced with the public API.
    Byte-order marks (BOM) removed from source files.
    Several broad except Exception blocks narrowed to expected exceptions. Boundary blocks in engine, app, and CLI stay broad but log errors.

Removed

    Root-level try_reporter.py and check.json (moved to tools/).
    Generated test outputs from the repository.
    Version labels ("SEO-V2") in code and reports.

Roadmap to 1.0.0

Versions follow the phase plan. Each completed roadmap task in Phase 0 gets its own minor release; later phases are released per phase.

    0.1.0: infrastructure basics (BOM removal, .gitignore, LICENSE, README, pyproject, CI). Done.
    0.2.0 to 0.6.0: pipeline and plugin registry, storage layer, project config, structured logging and issue codes, integration fixture server.
    1.0.0 criteria: Phases 0 to 3 complete, CI green on Ubuntu and Windows, stable CLI and public API, and a security review completed.
