from conftest import post
import translations


def test_tamil_is_a_language_option():
    import app as ledger_app
    assert "Tamil" in ledger_app.LANGUAGES


def test_translate_returns_tamil_for_known_key():
    assert translations.translate("nav_dashboard", "Tamil") == "டாஷ்போர்டு"


def test_translate_falls_back_to_english_for_unknown_key():
    assert translations.translate("totally_made_up_key", "Tamil") == "totally_made_up_key"


def test_translate_falls_back_to_english_for_unknown_language():
    assert translations.translate("nav_dashboard", "Klingon") == "Dashboard"


def test_switching_language_actually_changes_rendered_page(alice):
    before = alice.get("/dashboard").get_data(as_text=True)
    assert "Dashboard" in before

    post(alice, "/settings/profile", {"name": "Alice", "currency": "INR", "language": "Tamil"})

    after = alice.get("/dashboard").get_data(as_text=True)
    assert "டாஷ்போர்டு" in after
    assert "நிகர மதிப்பு" in after


def test_all_declared_languages_have_full_translation_tables():
    import app as ledger_app
    base_keys = set(translations.TRANSLATIONS["en"].keys())
    for lang in ledger_app.LANGUAGES:
        code = translations.LANGUAGE_CODES[lang]
        assert code in translations.TRANSLATIONS, f"missing table for {lang}"
        missing = base_keys - set(translations.TRANSLATIONS[code].keys())
        assert not missing, f"{lang} is missing keys: {missing}"
