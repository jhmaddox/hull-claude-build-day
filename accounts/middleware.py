"""Per-request current-org resolution.  [stable contract]"""

from .models import Membership, Org, set_current_org, clear_current_org


class CurrentOrgMiddleware:
    """Resolve the active Org for each request and expose it as ``request.org``
    (also stored in a thread-local for managers/services).

    Active org = session['org_id'] if the user is a member, else their first
    membership. Anonymous requests have ``request.org = None``.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        org = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            org_id = request.session.get("org_id")
            qs = Membership.objects.filter(user=user).select_related("org")
            membership = None
            if org_id:
                membership = qs.filter(org_id=org_id).first()
            if membership is None:
                membership = qs.first()
            if membership is not None:
                org = membership.org
                request.session["org_id"] = org.id
                request.membership = membership
        request.org = org
        set_current_org(org)
        try:
            return self.get_response(request)
        finally:
            clear_current_org()
