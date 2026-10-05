import csv
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import ProtectedError, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .forms import RegistrationForm, CategoryForm, TransactionForm, LimitForm, FilterForm
from .models import Category, Transaction, BudgetLimit, Kind
from .services import totals, limit_statuses, month_end

@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            for name, kind in [("Зарплата", "income"), ("Другие доходы", "income"),
                               ("Продукты", "expense"), ("Транспорт", "expense"), ("Другое", "expense")]:
                Category.objects.create(owner=user, name=name, kind=kind)
        login(request, user)
        return redirect("dashboard")
    return render(request, "registration/register.html", {"form": form})

@login_required
def dashboard(request):
    qs = Transaction.objects.filter(owner=request.user).select_related("category")
    month = timezone.localdate().replace(day=1)
    return render(request, "finance/dashboard.html", {"overall": totals(qs),
        "current": totals(qs.filter(date__gte=month, date__lt=month_end(month))), "month": month,
        "recent": qs[:6], "limits": limit_statuses(request.user, month)})

def filtered(request):
    form = FilterForm(request.GET, user=request.user)
    qs = Transaction.objects.filter(owner=request.user).select_related("category")
    if form.is_valid():
        for name, lookup in [("start", "date__gte"), ("end", "date__lte"), ("kind", "kind"), ("category", "category")]:
            if form.cleaned_data.get(name):
                qs = qs.filter(**{lookup: form.cleaned_data[name]})
    else:
        qs = qs.none()
    return form, qs

@login_required
def transactions(request):
    form, qs = filtered(request)
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "finance/transactions.html", {"filter_form": form,
        "page": Paginator(qs, 25).get_page(request.GET.get("page")), "summary": totals(qs),
        "query": query.urlencode(), "overall": totals(Transaction.objects.filter(owner=request.user))})

@login_required
@require_http_methods(["GET", "POST"])
def transaction_edit(request, pk=None):
    obj = get_object_or_404(Transaction, pk=pk, owner=request.user) if pk else Transaction(owner=request.user)
    with transaction.atomic():
        form = TransactionForm(request.POST if request.method == "POST" else None, instance=obj, user=request.user)
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, "Операция сохранена.")
            return redirect("transactions")
    return render(request, "finance/form.html", {"form": form, "title": "Изменить операцию" if pk else "Новая операция",
        "cancel_url": reverse("transactions"), "category_data": list(Category.objects.filter(owner=request.user).values("id", "kind"))})

@login_required
@require_http_methods(["GET", "POST"])
def category_edit(request, pk=None):
    obj = get_object_or_404(Category, pk=pk, owner=request.user) if pk else Category(owner=request.user)
    with transaction.atomic():
        form = CategoryForm(request.POST if request.method == "POST" else None, instance=obj)
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, "Категория сохранена.")
            return redirect("categories")
    return render(request, "finance/form.html", {"form": form, "title": "Изменить категорию" if pk else "Новая категория",
                                                "cancel_url": reverse("categories")})

@login_required
def categories(request):
    return render(request, "finance/categories.html", {"categories": Category.objects.filter(owner=request.user)})

@login_required
@require_http_methods(["GET", "POST"])
def limit_edit(request, pk=None):
    obj = get_object_or_404(BudgetLimit, pk=pk, owner=request.user) if pk else BudgetLimit(owner=request.user)
    with transaction.atomic():
        form = LimitForm(request.POST if request.method == "POST" else None, instance=obj, user=request.user)
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, "Лимит сохранён.")
            return redirect("limits")
    return render(request, "finance/form.html", {"form": form, "title": "Изменить лимит" if pk else "Новый лимит",
                                                "cancel_url": reverse("limits")})

@login_required
def limits(request):
    return render(request, "finance/limits.html", {"limits": limit_statuses(request.user)})

@login_required
@require_http_methods(["GET", "POST"])
def delete(request, entity, pk):
    model, destination, label = {
        "transaction": (Transaction, "transactions", "операцию"),
        "category": (Category, "categories", "категорию"),
        "limit": (BudgetLimit, "limits", "лимит"),
    }[entity]
    obj = get_object_or_404(model, owner=request.user, pk=pk)
    if request.method == "POST":
        try:
            with transaction.atomic():
                obj.delete()
            messages.success(request, "Запись удалена.")
        except ProtectedError:
            messages.error(request, "Категория используется в операциях или лимитах. Сначала перенесите операции и удалите связанные лимиты.")
        return redirect(destination)
    return render(request, "finance/delete.html", {"object": obj, "label": label, "cancel_url": reverse(destination)})

@login_required
def report(request):
    form, qs = filtered(request)
    spending = list(qs.filter(kind=Kind.EXPENSE).values("category__name").annotate(total=Sum("amount_cents")).order_by("-total", "category__name"))
    total = sum(row["total"] for row in spending)
    for row in spending:
        row["percent"] = round(Decimal(row["total"]) * 100 / total, 1) if total else 0
    return render(request, "finance/report.html", {"filter_form": form, "spending": spending,
        "summary": totals(qs), "query": request.GET.urlencode()})

def csv_safe(value):
    # Prevent formulas in spreadsheet programs, including whitespace-prefixed formulas.
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text

@login_required
def export_csv(request):
    form, qs = filtered(request)
    if not form.is_valid():
        return HttpResponse("Некорректные параметры фильтра.", status=400)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="operations.csv"'
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(["Дата", "Тип", "Категория", "Сумма, руб.", "Комментарий"])
    for item in qs.iterator():
        writer.writerow([item.date.isoformat(), item.get_kind_display(), csv_safe(item.category.name),
                         f"{item.amount:.2f}".replace(".", ","), csv_safe(item.comment)])
    return response
