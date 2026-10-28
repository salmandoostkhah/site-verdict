"""Static checks for app.py: it must parse and import-declare cleanly without running the GUI."""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app.py"


def test_app_py_parses():
    source = APP.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(APP))
    assert tree is not None


def test_app_py_has_no_top_level_side_effect_calls():
    """Only definitions/imports at module level; running the GUI must be guarded."""
    tree = ast.parse(APP.read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            name = getattr(node.value.func, "id", None) or getattr(node.value.func, "attr", "")
            assert name not in {"run", "main", "exec_"}, f"unguarded top-level call: {name}"


def test_app_py_imports_resolve_to_known_modules():
    tree = ast.parse(APP.read_text(encoding="utf-8-sig"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("seo_core"):
            names.add(node.module)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("seo_core"):
                    names.add(a.name)
    import importlib.util
    for mod in names:
        assert importlib.util.find_spec(mod) is not None, f"missing module {mod}"


def _get_val_calls():
    """همه فراخوانی‌های _get_val(obj, 'key', default?) در app.py."""
    tree = ast.parse(APP.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_get_val"
                and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)):
            yield node


def test_boolean_flags_default_to_false():
    """پیش‌فرض «—» truthy است و قبلاً باعث نمایش اشتباه noindex/فشرده‌سازی می‌شد."""
    found = set()
    for call in _get_val_calls():
        key = call.args[1].value
        if key in {"is_noindex", "is_compressed"}:
            found.add(key)
            assert len(call.args) >= 3, f"{key} without explicit default"
            assert isinstance(call.args[2], ast.Constant) and call.args[2].value is False
    assert found == {"is_noindex", "is_compressed"}


def test_asset_metrics_read_from_assets_object():
    from seo_core.models import AssetMetrics, TechnicalMetrics

    asset_keys = {"total_css", "total_js", "total_requests", "render_blocking_js_count"}
    for call in _get_val_calls():
        if call.args[1].value in asset_keys:
            assert getattr(call.args[0], "id", None) == "assets", ast.unparse(call)
        if call.args[1].value == "assets":
            assert getattr(call.args[0], "id", None) == "tech"

    # و این کلیدها واقعاً روی مدل وجود دارند
    from seo_core.access import get_val as _get_val
    tech = TechnicalMetrics(assets=AssetMetrics(total_css=2, total_js=3,
                                                total_requests=9, render_blocking_js_count=1))
    assets = _get_val(tech, "assets", None)
    assert [_get_val(assets, k, 0) for k in
            ("total_css", "total_js", "total_requests", "render_blocking_js_count")] == [2, 3, 9, 1]
    assert _get_val(None, "total_css", 0) == 0