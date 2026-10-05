from datetime import date
from django.db.models import Sum, Q
from .models import Transaction, BudgetLimit, Kind

def totals(qs):
    values = qs.aggregate(income=Sum("amount_cents", filter=Q(kind=Kind.INCOME)),
                          expense=Sum("amount_cents", filter=Q(kind=Kind.EXPENSE)))
    income, expense = values["income"] or 0, values["expense"] or 0
    return {"income": income, "expense": expense, "balance": income - expense}

def month_end(month):
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)

def limit_statuses(user, month=None):
    limits = BudgetLimit.objects.filter(owner=user).select_related("category")
    if month:
        limits = limits.filter(month=month)
    result = []
    for limit in limits:
        spent = Transaction.objects.filter(owner=user, category=limit.category, kind=Kind.EXPENSE,
                                            date__gte=limit.month, date__lt=month_end(limit.month)).aggregate(n=Sum("amount_cents"))["n"] or 0
        result.append({"limit": limit, "spent": spent, "remaining": max(0, limit.amount_cents - spent),
                       "excess": max(0, spent - limit.amount_cents), "reached": spent >= limit.amount_cents,
                       "percent": min(100, spent * 100 // limit.amount_cents)})
    return result
