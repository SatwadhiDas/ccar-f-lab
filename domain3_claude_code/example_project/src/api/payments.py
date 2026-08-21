"""Sample handler so the path-scoped rules have something to match."""


async def post_payment(request):
    return {"ok": True}
