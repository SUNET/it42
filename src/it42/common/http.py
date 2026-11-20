from collections.abc import Callable
from functools import wraps
from typing import Concatenate

from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.utils.cache import patch_vary_headers


def board_card[**P](
    view: Callable[Concatenate[HttpRequest, P], HttpResponse],
) -> Callable[Concatenate[HttpRequest, P], HttpResponse]:
    """Render a detail view inside its own site's board, using the normal access checks."""

    @wraps(view)
    def wrapper(request: HttpRequest, /, *args: P.args, **kwargs: P.kwargs) -> HttpResponse:
        if request.method != "GET" or request.GET.get("board_card") != "1":
            return view(request, *args, **kwargs)
        embedded = (
            request.headers.get("Sec-Fetch-Dest") == "iframe"
            and request.headers.get("Sec-Fetch-Site") == "same-origin"
        )
        if embedded:
            request.META["IT42_BOARD_CARD"] = True
        response = view(request, *args, **kwargs)
        if embedded and response.status_code == 200:
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
        patch_vary_headers(response, ("Sec-Fetch-Dest", "Sec-Fetch-Site"))
        return response

    return wrapper


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
