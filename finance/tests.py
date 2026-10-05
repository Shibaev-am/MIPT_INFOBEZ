import csv
import io
import sqlite3
import tempfile
from contextlib import closing
from datetime import date
from pathlib import Path
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from .models import Category, Transaction, BudgetLimit
from .services import totals, limit_statuses
from .templatetags.money import money
from scripts.database import backup, restore

@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class FinanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="Test-password-12345")
        cls.bob = User.objects.create_user("bob", password="Other-password-12345")
        cls.food = Category.objects.create(owner=cls.alice, name="Продукты", kind="expense")
        cls.salary = Category.objects.create(owner=cls.alice, name="Зарплата", kind="income")
        cls.bobs_category = Category.objects.create(owner=cls.bob, name="Чужая категория", kind="expense")

    def setUp(self):
        self.client.force_login(self.alice)

    def post_operation(self, **changes):
        values = {"kind": "expense", "category": self.food.pk, "date": "2026-10-05", "amount": "1500.00", "comment": "Тест"}
        values.update(changes)
        return self.client.post(reverse("transaction_create"), values)

    def operation(self, cents=150000, **changes):
        values = {"owner": self.alice, "category": self.food, "kind": "expense", "amount_cents": cents, "date": date(2026,10,5)}
        values.update(changes)
        return Transaction.objects.create(**values)

    def test_register_login_and_logout(self):
        self.client.logout()
        response = self.client.post(reverse("register"), {"username": "student", "password1": "Study-budget-2026!", "password2": "Study-budget-2026!"})
        self.assertRedirects(response, reverse("dashboard"))
        user = User.objects.get(username="student")
        self.assertTrue(user.check_password("Study-budget-2026!"))
        self.assertNotEqual(user.password, "Study-budget-2026!")
        self.assertEqual(Category.objects.filter(owner=user).count(), 5)
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code,302)
        self.assertFalse(self.client.login(username="student", password="incorrect"))
        self.assertTrue(self.client.login(username="student", password="Study-budget-2026!"))

    def test_logout_requires_post(self):
        self.assertEqual(self.client.get(reverse("logout")).status_code,405)

    def test_unauthenticated_pages_redirect(self):
        self.client.logout()
        for name in ["dashboard", "transactions", "transaction_create", "categories", "limits", "report", "export_csv"]:
            self.assertEqual(self.client.get(reverse(name)).status_code,302)

    def test_create_edit_delete_and_balance(self):
        self.assertEqual(self.post_operation(kind="income", category=self.salary.pk, amount="10000").status_code,302)
        self.assertEqual(self.post_operation().status_code,302)
        expense = Transaction.objects.get(kind="expense")
        self.assertEqual(totals(Transaction.objects.all())["balance"],850000)
        response = self.client.post(reverse("transaction_edit",args=[expense.pk]), {"kind":"expense", "category":self.food.pk,"amount":"2000", "date":"2026-10-05"})
        self.assertEqual(response.status_code,302)
        self.assertEqual(totals(Transaction.objects.all())["balance"],800000)
        self.client.get(reverse("transaction_delete",args=[expense.pk]))
        self.assertTrue(Transaction.objects.filter(pk=expense.pk).exists())
        self.client.post(reverse("transaction_delete",args=[expense.pk]))
        self.assertEqual(totals(Transaction.objects.all())["balance"],1000000)

    def test_decimal_cents_exact(self):
        self.post_operation(amount="0.10")
        self.post_operation(amount="0.20")
        self.assertEqual(totals(Transaction.objects.all())["expense"],30)
        self.assertEqual(money(30),"0,30 ₽")
        self.assertEqual(money(-100001),"−1 000,01 ₽")

    def test_invalid_amounts_and_dates_rejected(self):
        for amount in ["0", "-1", "0.001", "NaN", "Infinity", "10000000000", "abc", ""]:
            with self.subTest(amount=amount):
                self.assertEqual(self.post_operation(amount=amount).status_code,200)
                self.assertEqual(Transaction.objects.count(),0)
        self.assertEqual(self.post_operation(date="2026-02-30").status_code,200)
        self.assertEqual(self.post_operation(date="").status_code,200)
        self.assertEqual(Transaction.objects.count(),0)

    def test_category_owner_and_type_validation(self):
        self.assertEqual(self.post_operation(category=self.bobs_category.pk).status_code,200)
        self.assertEqual(self.post_operation(category=self.salary.pk).status_code,200)
        self.assertEqual(Transaction.objects.count(),0)
        with self.assertRaises(ValidationError):
            self.operation(category=self.bobs_category)

    def test_tenant_isolation_in_all_pages_and_direct_requests(self):
        item = self.operation(comment="PRIVATE_COMMENT_42")
        limit = BudgetLimit.objects.create(owner=self.alice,category=self.food,month=date(2026,10,1),amount_cents=300000)
        self.client.force_login(self.bob)
        for name in ["dashboard","transactions","report","export_csv","limits","categories"]:
            response=self.client.get(reverse(name))
            self.assertNotContains(response,"PRIVATE_COMMENT_42")
            self.assertNotContains(response,"Продукты")
        for name, pk in [("transaction_edit",item.pk),("transaction_delete",item.pk),
                          ("category_edit",self.food.pk),("category_delete",self.food.pk),
                          ("limit_edit",limit.pk),("limit_delete",limit.pk)]:
            self.assertEqual(self.client.get(reverse(name,args=[pk])).status_code,404)
            self.assertEqual(self.client.post(reverse(name,args=[pk]),{}).status_code,404)
        self.assertTrue(Transaction.objects.filter(pk=item.pk).exists())
        response=self.client.get(reverse("transactions"),{"category":self.food.pk})
        self.assertEqual(response.context["page"].paginator.count,0)
        self.assertEqual(self.client.get(reverse("export_csv"),{"category":self.food.pk}).status_code,400)

    def test_owner_cannot_be_forged(self):
        self.post_operation(owner=self.bob.pk)
        self.assertEqual(Transaction.objects.get().owner,self.alice)

    def test_categories_rename_protect_and_duplicate(self):
        item=self.operation()
        url=reverse("category_edit",args=[self.food.pk])
        self.assertEqual(self.client.post(url,{"name":"Питание","kind":"expense"}).status_code,302)
        item.refresh_from_db()
        self.assertEqual(item.category.name,"Питание")
        response=self.client.post(reverse("category_delete",args=[self.food.pk]),follow=True)
        self.assertContains(response,"Категория используется")
        self.assertTrue(Category.objects.filter(pk=self.food.pk).exists())
        self.assertEqual(self.client.post(url,{"name":"Питание","kind":"income"}).status_code,200)
        response=self.client.post(reverse("category_create"),{"name":" Питание ","kind":"expense"})
        self.assertContains(response,"Такая категория уже есть")

    def test_unused_category_can_be_deleted(self):
        self.client.post(reverse("category_delete",args=[self.food.pk]))
        self.assertFalse(Category.objects.filter(pk=self.food.pk).exists())

    def test_filters_and_global_balance(self):
        self.operation(1000000,kind="income",category=self.salary)
        self.operation(150000)
        self.operation(50000,date=date(2026,9,30))
        response=self.client.get(reverse("transactions"),{"start":"2026-10-01","end":"2026-10-31","kind":"expense"})
        self.assertEqual(response.context["page"].paginator.count,1)
        self.assertEqual(response.context["summary"]["expense"],150000)
        self.assertEqual(response.context["overall"]["balance"],800000)

    def test_invalid_filter_does_not_silently_export_everything(self):
        self.operation()
        for query in [{"start":"bad"},{"start":"2026-10-06","end":"2026-10-01"},{"kind":"invalid"}]:
            self.assertEqual(self.client.get(reverse("transactions"),query).context["page"].paginator.count,0)
            self.assertEqual(self.client.get(reverse("export_csv"),query).status_code,400)

    def test_report_shares_and_csv(self):
        transport=Category.objects.create(owner=self.alice,name="Транспорт",kind="expense")
        self.operation(150000)
        self.operation(50000,category=transport)
        response=self.client.get(reverse("report"))
        self.assertEqual([row["percent"] for row in response.context["spending"]],[75,25])
        response=self.client.get(reverse("export_csv"),{"category":self.food.pk})
        rows=list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")),delimiter=";"))
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[1][2:4],["Продукты","1500,00"])

    def test_csv_formula_injection_neutralized(self):
        self.operation(comment=' =HYPERLINK("bad")')
        response=self.client.get(reverse("export_csv"))
        rows=list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")),delimiter=";"))
        self.assertTrue(rows[1][4].startswith("'"))

    def test_comment_html_is_escaped(self):
        self.operation(comment='<script>alert("x")</script>')
        response=self.client.get(reverse("transactions"))
        self.assertNotContains(response,'<script>alert(')
        self.assertContains(response,'&lt;script&gt;')

    def test_limit_crud_duplicate_and_month_boundaries(self):
        response=self.client.post(reverse("limit_create"),{"category":self.food.pk,"month":"2026-10","amount":"3000"})
        self.assertEqual(response.status_code,302)
        limit=BudgetLimit.objects.get()
        self.operation(290000)
        self.operation(800000,date=date(2026,9,30))
        self.operation(700000,date=date(2026,11,1))
        status=limit_statuses(self.alice,date(2026,10,1))[0]
        self.assertEqual(status["spent"],290000)
        self.assertFalse(status["reached"])
        self.operation(10000)
        self.assertTrue(limit_statuses(self.alice)[0]["reached"])
        self.assertEqual(limit_statuses(self.alice)[0]["excess"],0)
        self.operation(20000)
        self.assertEqual(limit_statuses(self.alice)[0]["excess"],20000)
        response=self.client.post(reverse("limit_create"),{"category":self.food.pk,"month":"2026-10","amount":"4000"})
        self.assertContains(response,"уже задан лимит")
        self.assertEqual(self.client.post(reverse("limit_edit",args=[limit.pk]),{"category":self.food.pk,"month":"2026-10","amount":"4000"}).status_code,302)
        self.assertEqual(BudgetLimit.objects.get().amount_cents,400000)
        self.client.post(reverse("limit_delete",args=[limit.pk]))
        self.assertEqual(BudgetLimit.objects.count(),0)

    def test_limit_rejects_foreign_or_income_category(self):
        for cat in [self.salary,self.bobs_category]:
            response=self.client.post(reverse("limit_create"),{"category":cat.pk,"month":"2026-10","amount":"3000"})
            self.assertEqual(response.status_code,200)
        self.assertEqual(BudgetLimit.objects.count(),0)

    def test_csrf_blocks_mutations(self):
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.alice)
        self.assertEqual(client.post(reverse("transaction_create"),{"kind":"expense","category":self.food.pk,"amount":"10","date":"2026-10-05"}).status_code,403)
        self.assertEqual(Transaction.objects.count(),0)

    def test_database_rejects_nonpositive_amount(self):
        item=self.operation()
        with self.assertRaises(IntegrityError),transaction.atomic():
            Transaction.objects.filter(pk=item.pk).update(amount_cents=0)
        item.refresh_from_db()
        self.assertEqual(item.amount_cents,150000)

    def test_atomic_rollback_keeps_balance(self):
        self.operation()
        try:
            with transaction.atomic():
                self.operation(30000)
                raise RuntimeError("Simulated interruption")
        except RuntimeError:
            pass
        self.assertEqual(totals(Transaction.objects.all())["expense"],150000)

    def test_pagination(self):
        for _ in range(26): self.operation(100)
        response=self.client.get(reverse("transactions"))
        self.assertEqual(len(response.context["page"]),25)
        self.assertEqual(len(self.client.get(reverse("transactions"),{"page":2}).context["page"]),1)

    def test_empty_pages_render(self):
        for name in ["dashboard","transactions","report","limits","categories","transaction_create","category_create","limit_create"]:
            self.assertEqual(self.client.get(reverse(name)).status_code,200)

    def test_demo_never_overwrites_existing_operations(self):
        from django.core.management.base import CommandError
        call_command("seed_demo","alice",stdout=io.StringIO())
        self.assertEqual(Transaction.objects.filter(owner=self.alice).count(),4)
        with self.assertRaises(CommandError): call_command("seed_demo","alice")
        self.assertEqual(Transaction.objects.filter(owner=self.alice).count(),4)

    def test_backup_restore_and_invalid_backup(self):
        # Serialize the migrated test database, including real schema and constraints.
        self.operation()
        from django.db import connection
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); db=root/"source.sqlite3"; copy=root/"backup.sqlite3"
            raw=connection.connection
            with closing(sqlite3.connect(db)) as target, target:
                target.executescript("\n".join(raw.iterdump()))
            backup(db,copy)
            with closing(sqlite3.connect(db)) as target, target:
                target.execute("DELETE FROM finance_transaction")
            restore(copy,db,root/"safety")
            with closing(sqlite3.connect(db)) as target, target:
                self.assertEqual(target.execute("SELECT amount_cents FROM finance_transaction").fetchone()[0],150000)
            self.assertEqual(len(list((root/"safety").glob("*.sqlite3"))),1)
            invalid=root/"invalid.sqlite3"; invalid.write_bytes(b"not a database")
            before=db.read_bytes()
            with self.assertRaises(sqlite3.Error): restore(invalid,db,root/"safety")
            self.assertEqual(db.read_bytes(),before)
            with self.assertRaises(FileExistsError): backup(db,copy)
