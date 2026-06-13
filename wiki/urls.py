from django.urls import path

from . import views

app_name = "wiki"

urlpatterns = [
    path("", views.index, name="index"),
    path("search/", views.search, name="search"),
    # spaces
    path("spaces/new/", views.space_new, name="space_new"),
    path("space/<slug:slug>/", views.space_detail, name="space"),
    # pages
    path("pages/new/", views.page_new, name="page_new"),
    path("page/<int:pk>/", views.page_detail, name="page"),
    path("page/<int:pk>/edit/", views.page_edit, name="page_edit"),
    path("page/<int:pk>/delete/", views.page_delete, name="page_delete"),
    # HTMX edit-in-place fragments
    path("page/<int:pk>/inline/", views.page_edit_inline, name="page_edit_inline"),
    path("page/<int:pk>/body/", views.page_body, name="page_body"),
    # history
    path("page/<int:pk>/history/", views.page_history, name="page_history"),
    path("page/<int:pk>/v/<int:number>/", views.revision_detail, name="revision"),
    path(
        "page/<int:pk>/v/<int:number>/restore/",
        views.revision_restore,
        name="revision_restore",
    ),
]
