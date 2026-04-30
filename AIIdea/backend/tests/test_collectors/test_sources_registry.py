from src.collectors.sources_registry import SOURCES


def test_names_are_unique():
    names = [s.name for s in SOURCES]
    assert len(names) == len(set(names)), "duplicate source names in SOURCES"


def test_kinds_are_valid():
    for s in SOURCES:
        assert s.kind in {"rss", "html", "json"}, f"bad kind {s.kind} on {s.name}"


def test_rss_sources_have_url():
    for s in SOURCES:
        if s.kind == "rss":
            assert s.url.startswith(("http://", "https://")), s.name


def test_html_sources_have_required_selectors():
    for s in SOURCES:
        if s.kind != "html":
            continue
        assert s.item_selector, f"{s.name} missing item_selector"
        # link source: either the item itself is the anchor, or link_selector set,
        # or (fallback) the item contains an <a> by default
        has_link_rule = s.link_is_item or s.link_selector is not None
        assert has_link_rule or s.item_selector is not None, s.name
        has_title_rule = (
            s.title_is_link_text or s.title_selector is not None
        )
        assert has_title_rule, f"{s.name} missing a title rule"


def test_json_sources_have_required_fields():
    for s in SOURCES:
        if s.kind != "json":
            continue
        assert s.title_field, f"{s.name} missing title_field"
        assert s.url_field, f"{s.name} missing url_field"


def test_source_config_is_frozen():
    cfg = SOURCES[0]
    try:
        cfg.name = "mutated"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("SourceConfig should be frozen")
