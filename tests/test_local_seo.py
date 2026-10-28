"""Tests for the Local SEO analyzer (pure HTML input, no network)."""
from seo_core.analyzers.local_seo import analyze_local_seo
from seo_core.models import LocalSEOMetrics

LOCAL_HTML = """<html lang="fa-IR"><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "LocalBusiness",
 "name": "Test Shop", "telephone": "+98-21-12345678",
 "email": "info@example.com",
 "address": {"@type": "PostalAddress", "streetAddress": "Valiasr 1",
             "addressLocality": "Tehran"},
 "geo": {"@type": "GeoCoordinates", "latitude": 35.7, "longitude": 51.4}}
</script>
<meta name="geo.position" content="35.7;51.4">
</head><body>
<a href="tel:+982112345678">call us</a>
<a href="mailto:sales@example.com">mail</a>
<iframe src="https://www.google.com/maps/embed?pb=1"></iframe>
</body></html>"""


def test_empty_html_returns_no_local_signals():
    metrics, issues, warnings = analyze_local_seo("", "https://example.com")
    assert metrics["has_local_schema"] is False
    assert metrics["detected_telephones"] == []
    assert metrics["has_google_maps_embed"] is False
    assert metrics["local_score"] <= 20


def test_detects_local_business_schema_and_business_name():
    metrics, _, _ = analyze_local_seo(LOCAL_HTML, "https://example.com")
    assert metrics["has_local_schema"] is True
    assert "LocalBusiness" in metrics["schema_types"]
    assert metrics["business_name"] == "Test Shop"


def test_detects_phone_and_emails():
    metrics, _, _ = analyze_local_seo(LOCAL_HTML, "https://example.com")
    assert any("12345678" in p or "2112345678" in p for p in metrics["detected_telephones"])
    assert "info@example.com" in metrics["emails"]
    assert "sales@example.com" in metrics["emails"]


def test_detects_geo_meta_and_maps_embed():
    metrics, _, _ = analyze_local_seo(LOCAL_HTML, "https://example.com")
    assert metrics["has_geo_meta"] is True
    assert metrics["has_google_maps_embed"] is True


def test_score_is_bounded_and_metrics_validate_as_model():
    metrics, issues, warnings = analyze_local_seo(LOCAL_HTML, "https://example.com")
    assert 0 <= metrics["local_score"] <= 100
    assert isinstance(issues, list) and isinstance(warnings, list)
    model = LocalSEOMetrics(**metrics)
    assert model.has_local_schema is True


def test_malformed_html_does_not_raise():
    metrics, _, _ = analyze_local_seo("<html><<<>>> <script type='application/ld+json'>{bad",
                                      "https://example.com")
    assert metrics["has_local_schema"] is False