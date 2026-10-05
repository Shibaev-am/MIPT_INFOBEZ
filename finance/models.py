from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

MAX_CENTS = 999_999_999_999

class Kind(models.TextChoices):
    INCOME = "income", "Доход"
    EXPENSE = "expense", "Расход"

class Category(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField("Название", max_length=60)
    kind = models.CharField("Тип", max_length=7, choices=Kind.choices)

    class Meta:
        ordering = ["kind", "name"]
        constraints = [models.UniqueConstraint(fields=["owner", "name", "kind"], name="unique_user_category"),
                       models.CheckConstraint(condition=Q(kind__in=Kind.values), name="valid_category_kind")]

    def __str__(self):
        return self.name

    def clean(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValidationError({"name": "Введите название категории."})
        if self.pk:
            old = Category.objects.get(pk=self.pk)
            if old.owner_id != self.owner_id:
                raise ValidationError("Нельзя изменить владельца категории.")
            if old.kind != self.kind and (self.transactions.exists() or self.limits.exists()):
                raise ValidationError({"kind": "Тип используемой категории изменить нельзя."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class Transaction(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="transactions", verbose_name="Категория")
    kind = models.CharField("Тип", max_length=7, choices=Kind.choices)
    amount_cents = models.BigIntegerField()
    date = models.DateField("Дата", default=timezone.localdate)
    comment = models.CharField("Комментарий", max_length=300, blank=True)

    class Meta:
        ordering = ["-date", "-pk"]
        indexes = [models.Index(fields=["owner", "date"])]
        constraints = [
            models.CheckConstraint(condition=Q(amount_cents__gt=0, amount_cents__lte=MAX_CENTS), name="valid_transaction_amount"),
            models.CheckConstraint(condition=Q(kind__in=Kind.values), name="valid_transaction_kind"),
        ]

    @property
    def amount(self):
        return Decimal(self.amount_cents) / 100

    def clean(self):
        if self.category_id:
            if self.category.owner_id != self.owner_id:
                raise ValidationError({"category": "Категория недоступна."})
            if self.category.kind != self.kind:
                raise ValidationError({"category": "Тип категории не совпадает с типом операции."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class BudgetLimit(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="limits", verbose_name="Категория")
    month = models.DateField("Месяц")
    amount_cents = models.BigIntegerField()

    class Meta:
        ordering = ["-month", "category__name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "category", "month"], name="unique_month_limit"),
            models.CheckConstraint(condition=Q(amount_cents__gt=0, amount_cents__lte=MAX_CENTS), name="valid_limit_amount"),
        ]

    def clean(self):
        if self.month and self.month.day != 1:
            raise ValidationError({"month": "Укажите первый день месяца."})
        if self.category_id and (self.category.owner_id != self.owner_id or self.category.kind != Kind.EXPENSE):
            raise ValidationError({"category": "Выберите свою категорию расходов."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
