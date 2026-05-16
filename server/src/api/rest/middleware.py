"""
REST API middleware for authentication and request processing.
"""

from aiohttp import web

from ...db.models.rest_ext.api_key import ApiKey
from .helpers import HTTP_UNAUTHORIZED, error


@web.middleware
async def api_key_middleware(request: web.Request, handler):
    """
    Middleware to validate API key for all /api/v1/* routes.

    Checks for X-API-Key header, validates against database,
    and attaches ApiKey record to request for downstream handlers.

    Exception:
        - POST /api/v1/auth/keys is passed through to handler with api_key=None
          or validated key (if header present). Handler decides auth mode:
          1) Credential-based (username+password in body)
          2) Bootstrap (no keys exist)
          3) API key auth (X-API-Key header)

    Args:
        request: aiohttp Request
        handler: Next handler in chain

    Returns:
        Response from handler or 401 error
    """
    # Only apply to /api/v1/* paths
    if not request.path.startswith("/api/v1/"):
        return await handler(request)

    # Exception for POST /auth/keys: Let the handler decide auth mode
    # Handler supports 3 modes: credential-based, bootstrap, or API key
    if request.method == "POST" and request.path == "/api/v1/auth/keys":
        # Pass through to handler with api_key=None
        # Handler will check: 1) credentials, 2) bootstrap, 3) API key header
        api_key_value = request.headers.get("X-API-Key")
        if api_key_value:
            # Has API key header - validate it
            try:
                api_key = ApiKey.get(ApiKey.key == api_key_value)
                request["api_key"] = api_key
            except ApiKey.DoesNotExist:
                request["api_key"] = None
        else:
            # No API key header - handler will check credentials/bootstrap
            request["api_key"] = None
        return await handler(request)

    # Extract API key from header
    api_key_value = request.headers.get("X-API-Key")
    if not api_key_value:
        return error(
            "Missing X-API-Key header",
            code="UNAUTHORIZED",
            status=HTTP_UNAUTHORIZED,
        )

    # Validate API key
    try:
        api_key = ApiKey.get(ApiKey.key == api_key_value)
    except ApiKey.DoesNotExist:
        return error(
            "Invalid API key",
            code="UNAUTHORIZED",
            status=HTTP_UNAUTHORIZED,
        )

    # Attach API key to request for downstream use
    request["api_key"] = api_key

    # Continue to handler
    return await handler(request)
