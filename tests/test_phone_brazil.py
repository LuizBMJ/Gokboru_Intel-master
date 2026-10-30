from __future__ import annotations

from pathlib import Path

from moriarty.providers.phonenumbers_provider import PhoneNumbersProvider


def test_brazilian_mobile_with_international_prefix() -> None:
    result = PhoneNumbersProvider().analyze("+55 (11) 91234-5678")

    assert result.e164 == "+5511912345678"
    assert result.region_code == "BR"
    assert result.country_code == 55
    assert result.number_type == "mobile"
    assert result.is_valid is True
    assert result.is_mobile is True
    assert result.national_format == "(11) 91234-5678"


def test_brazilian_national_number_uses_br_region() -> None:
    result = PhoneNumbersProvider().analyze("011 91234-5678", "BR")

    assert result.e164 == "+5511912345678"
    assert result.region_code == "BR"
    assert result.is_mobile is True


def test_brazilian_landline_and_toll_free_are_supported() -> None:
    provider = PhoneNumbersProvider()
    landline = provider.analyze("(11) 3456-7890", "BR")
    toll_free = provider.analyze("0800 123 4567", "BR")

    assert landline.e164 == "+551134567890"
    assert landline.is_fixed_line is True
    assert toll_free.e164 == "+558001234567"
    assert toll_free.is_toll_free is True


def test_brazil_is_available_in_web_and_tui_selectors() -> None:
    root = Path(__file__).resolve().parents[1]
    web = (root / "src" / "moriarty" / "web_static" / "index.html").read_text(encoding="utf-8")
    tui = (root / "src" / "moriarty" / "tui.py").read_text(encoding="utf-8")

    assert '<option value="BR">BR +55</option>' in web
    assert '("BR +55","BR")' in tui
