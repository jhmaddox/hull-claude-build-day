def helm_globals(request):
    """Inject globals available in every template."""
    return {
        "HELM_PRODUCT": "Helm",
        "HELM_TAGLINE": "The autonomous software operating system",
    }
