from django.urls import path
from . import views
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("operations/", views.transactions, name="transactions"),
    path("operations/new/", views.transaction_edit, name="transaction_create"),
    path("operations/<int:pk>/edit/", views.transaction_edit, name="transaction_edit"),
    path("operations/<int:pk>/delete/", views.delete, {"entity": "transaction"}, name="transaction_delete"),
    path("categories/", views.categories, name="categories"),
    path("categories/new/", views.category_edit, name="category_create"),
    path("categories/<int:pk>/edit/", views.category_edit, name="category_edit"),
    path("categories/<int:pk>/delete/", views.delete, {"entity": "category"}, name="category_delete"),
    path("limits/", views.limits, name="limits"),
    path("limits/new/", views.limit_edit, name="limit_create"),
    path("limits/<int:pk>/edit/", views.limit_edit, name="limit_edit"),
    path("limits/<int:pk>/delete/", views.delete, {"entity": "limit"}, name="limit_delete"),
    path("reports/", views.report, name="report"),
    path("export/", views.export_csv, name="export_csv"),
]
