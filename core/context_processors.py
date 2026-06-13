from django.conf import settings


def helm_globals(request):
    """Inject globals available in every template."""
    return {
        "HELM_PRODUCT": settings.HELM_PRODUCT_NAME,
        "HELM_TAGLINE": settings.HELM_PRODUCT_TAGLINE,
    }
