from django import template
register = template.Library()

@register.filter
def money(cents):
    # Integer arithmetic keeps even large aggregated balances exact.
    cents = int(cents or 0)
    sign = "−" if cents < 0 else ""
    rubles, kopecks = divmod(abs(cents), 100)
    return f"{sign}{rubles:,}".replace(",", " ") + f",{kopecks:02d} ₽"
