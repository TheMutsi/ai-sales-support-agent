"""Pictures for cards. The simulated shop has no product photos, so a plan's picture is drawn
here: a colored tile with its name. A real shop would send its own image URLs in the cards."""

from fastapi import APIRouter, HTTPException, Response

router = APIRouter()

_TILES = {
    "starter": ("#f8a899", "#d9625a"),
    "pro": ("#8f2a2e", "#c4655f"),
    "enterprise": ("#2b2d42", "#6a6f9c"),
}


def _svg(slug: str, light: str, dark: str) -> str:
    label = slug.capitalize()
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" role="img" '
        f'aria-label="{label} plan">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{light}"/>'
        f'<stop offset="1" stop-color="{dark}"/></linearGradient></defs>'
        '<rect width="400" height="400" rx="32" fill="url(#g)"/>'
        '<circle cx="200" cy="150" r="64" fill="#fff" fill-opacity=".9"/>'
        '<text x="200" y="168" text-anchor="middle" font-family="system-ui,sans-serif" font-size="56" '
        f'font-weight="800" fill="{dark}">M</text>'
        '<text x="200" y="300" text-anchor="middle" font-family="system-ui,sans-serif" font-size="44" '
        f'font-weight="700" fill="#fff">{label}</text></svg>'
    )


@router.get("/assets/products/{slug}.svg")
def product_image(slug: str) -> Response:
    tile = _TILES.get(slug)
    if tile is None:  # only the known plans: nothing from the URL reaches the markup
        raise HTTPException(status_code=404)
    return Response(
        _svg(slug, *tile),
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        },
    )
