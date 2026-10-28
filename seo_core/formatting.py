"""تبدیل ارقام برای یکدست‌کردن نمایش (همه ارقام فارسی) و پذیرش ورودی با هر دو نوع رقم."""

_LATIN_TO_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_FA_TO_LATIN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def to_fa_digits(value) -> str:
    """ارقام لاتین متن را به فارسی تبدیل می‌کند."""
    return str(value).translate(_LATIN_TO_FA)


def to_latin_digits(value) -> str:
    """ارقام فارسی/عربی متن را به لاتین تبدیل می‌کند (برای ورودی‌ها مثل URL)."""
    return str(value).translate(_FA_TO_LATIN)