from fastapi import APIRouter

from app.schemas.tools import CustomerListItem
from app.tools.customers import list_customers

router = APIRouter()


@router.get("/customers")
def get_customers() -> list[CustomerListItem]:
    return list_customers()
