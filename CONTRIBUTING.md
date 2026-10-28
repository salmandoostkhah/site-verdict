Contributing

Thanks for your interest in improving Site Verdict.
Setup

python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

Before opening a pull request

    Run the test suite: python -m pytest -q. All tests must pass.
    Add or update tests for any behavior change, especially scoring and HTTP/SSRF code.
    Keep changes focused; one concern per pull request.
    Write files as UTF-8 without BOM.
    Do not commit generated reports, caches, or .env files (see .gitignore).

Guidelines

    Network-facing code must go through seo_core/safe_http.py. Do not create raw httpx clients for user-supplied URLs.
    Catch only the exceptions you expect. Broad except Exception is reserved for the top-level boundaries (engine, app, CLI) and must log the error.
    Security issues: see SECURITY.md, not public issues.

License

By contributing, you agree that your contributions are licensed under the MIT License.