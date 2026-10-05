from decimal import Decimal
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Category, Transaction, BudgetLimit, Kind

class RegistrationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ["username", "password1", "password2"]

class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "kind"]

    def clean(self):
        data = super().clean()
        name = (data.get("name") or "").strip()
        data["name"] = name
        if Category.objects.filter(owner=self.instance.owner, name=name, kind=data.get("kind")).exclude(pk=self.instance.pk).exists():
            self.add_error("name", "Такая категория уже есть.")
        return data

class MoneyForm(forms.ModelForm):
    amount = forms.DecimalField(label="Сумма, ₽", max_digits=12, decimal_places=2,
                                min_value=Decimal("0.01"), max_value=Decimal("9999999999.99"),
                                widget=forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal"}))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.owner = user
        self.fields["category"].queryset = Category.objects.filter(owner=user)
        if self.instance.pk:
            self.initial["amount"] = Decimal(self.instance.amount_cents) / 100

    def clean(self):
        data = super().clean()
        if data.get("amount") is not None:
            self.instance.amount_cents = int(data["amount"] * 100)
        return data

class TransactionForm(MoneyForm):
    class Meta:
        model = Transaction
        fields = ["kind", "amount", "date", "category", "comment"]
        widgets = {"date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
                   "comment": forms.Textarea(attrs={"rows": 3})}

class LimitForm(MoneyForm):
    month = forms.DateField(label="Месяц", input_formats=["%Y-%m"],
                           widget=forms.DateInput(format="%Y-%m", attrs={"type": "month"}))
    class Meta:
        model = BudgetLimit
        fields = ["category", "month", "amount"]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(owner=user, kind=Kind.EXPENSE)
        if not self.instance.pk:
            self.initial.setdefault("month", timezone.localdate().replace(day=1))

    def clean(self):
        data = super().clean()
        if data.get("category") and data.get("month"):
            if BudgetLimit.objects.filter(owner=self.instance.owner, category=data["category"], month=data["month"]).exclude(pk=self.instance.pk).exists():
                self.add_error("month", "Для этой категории и месяца уже задан лимит.")
        return data

class FilterForm(forms.Form):
    start = forms.DateField(label="С", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="По", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    kind = forms.ChoiceField(label="Тип", required=False, choices=[("", "Все операции"), *Kind.choices])
    category = forms.ModelChoiceField(label="Категория", required=False, queryset=Category.objects.none(), empty_label="Все категории")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(owner=user)

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["start"] > data["end"]:
            raise forms.ValidationError("Дата начала должна быть не позже даты окончания.")
        return data
