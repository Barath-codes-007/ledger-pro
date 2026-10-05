def test_skip_link_present(alice):
    html = alice.get("/dashboard").get_data(as_text=True)
    assert 'class="skip-link"' in html and 'href="#main-content"' in html


def test_main_landmark_present(alice):
    html = alice.get("/dashboard").get_data(as_text=True)
    assert 'id="main-content"' in html and '<main' in html


def test_toasts_are_announced_to_screen_readers(alice):
    html = alice.get("/dashboard").get_data(as_text=True)
    assert 'aria-live="polite"' in html


def test_search_box_has_accessible_label(alice):
    html = alice.get("/dashboard").get_data(as_text=True)
    assert 'aria-label="Search transactions"' in html


def test_reduced_motion_and_focus_visible_rules_exist():
    css = open("static/css/style.css").read()
    assert "prefers-reduced-motion" in css
    assert ":focus-visible" in css


def test_theme_toggle_icon_does_not_tint_on_hover():
    css = open("static/css/style.css").read()
    # The hover rule should only change the border, never the icon/text color -
    # fa-sun tinted green at small size was being misread as a settings/gear icon.
    import re
    hover_rule = re.search(r"\.theme-toggle:hover,\s*\.icon-btn:hover\s*\{([^}]*)\}", css)
    assert hover_rule, "expected a combined hover rule for theme-toggle/icon-btn"
    assert not re.search(r"(?<!border-)\bcolor:", hover_rule.group(1))
