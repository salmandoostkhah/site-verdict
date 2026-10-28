Security Policy
Supported versions

Only the latest release on the main branch receives security fixes.
Reporting a vulnerability

Please do not open a public issue for security problems.

Report privately through GitHub's "Report a vulnerability" button (Security tab → Advisories), or contact the maintainer directly. Include:

    A description of the issue and its impact
    Steps to reproduce (a local target is preferred)
    Affected version or commit

You can expect an acknowledgement within 7 days. Fixes are released as soon as practical, and reporters are credited unless they prefer otherwise.
Scope notes

The HTTP layer blocks private, loopback and link-local targets (SSRF protection), pins resolved IPs per request, and bounds redirects and response size. Reports that bypass these controls are high priority.