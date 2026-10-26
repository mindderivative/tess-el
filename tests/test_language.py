import pytest

from tel import LANGUAGE, TelVersionError
from tel.language import SUPPORTED, check_language


def test_the_newest_language_is_supported():
    assert LANGUAGE == "0.1" and LANGUAGE in SUPPORTED


def test_a_supported_version_passes():
    check_language("0.1")


@pytest.mark.parametrize("bad", ["0.2", "1.0", "0", "", "0.1.0", " 0.1", "v0.1"])
def test_an_unsupported_or_malformed_version_is_refused(bad):
    with pytest.raises(TelVersionError) as raised:
        check_language(bad)
    assert raised.value.code == "unsupported-language"
    assert "0.1" in str(raised.value)


@pytest.mark.parametrize("bad", [0.1, 1, None, 0.10])
def test_a_version_that_is_not_text_is_refused_with_the_yaml_warning(bad):
    with pytest.raises(TelVersionError) as raised:
        check_language(bad)
    assert raised.value.code == "language-not-text"
    assert "YAML" in str(raised.value)
