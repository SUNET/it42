from collections.abc import Callable
from functools import wraps

from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed


def post_required[**P](
    view: Callable[P, HttpResponse],
) -> Callable[P, HttpResponse]:
    """Typed equivalent of django.views.decorators.http.require_POST."""

    @wraps(view)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> HttpResponse:
        request = args[0]
        if not isinstance(request, HttpRequest) or request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        return view(*args, **kwargs)

    return wrapper
