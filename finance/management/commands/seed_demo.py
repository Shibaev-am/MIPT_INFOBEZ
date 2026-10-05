from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from finance.models import Category, Transaction, BudgetLimit

class Command(BaseCommand):
    help = "Add fictional data to an existing empty account. Does not create passwords."

    def add_arguments(self, parser):
        parser.add_argument("username")

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            user = get_user_model().objects.get(username=options["username"])
        except get_user_model().DoesNotExist:
            raise CommandError("Create the account in the browser first.")
        if Transaction.objects.filter(owner=user).exists() or BudgetLimit.objects.filter(owner=user).exists():
            raise CommandError("This account already has financial data. Nothing was changed.")
        today = timezone.localdate()
        for name, kind, amount, days, comment in [
            ("Зарплата", "income", 6500000, 3, "Учебные данные"),
            ("Продукты", "expense", 285050, 2, "Покупки на неделю"),
            ("Транспорт", "expense", 65000, 1, "Проездной"),
            ("Другое", "expense", 120000, 0, "Книги"),
        ]:
            category, _ = Category.objects.get_or_create(owner=user, name=name, kind=kind)
            Transaction.objects.create(owner=user, category=category, kind=kind, amount_cents=amount,
                                       date=max(today.replace(day=1), today-timedelta(days=days)), comment=comment)
        food = Category.objects.get(owner=user, name="Продукты", kind="expense")
        BudgetLimit.objects.create(owner=user, category=food, month=today.replace(day=1), amount_cents=1000000)
        self.stdout.write(self.style.SUCCESS("Fictional demo data created."))
