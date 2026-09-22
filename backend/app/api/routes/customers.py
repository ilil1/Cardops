"""고객 연락 정책을 관리하는 최소 관리자 API입니다."""

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy.orm import Session

from .auth import require_roles
from ...database import get_db
from ...enums import UserRole
from ...models import Customer, User
from ...schemas import (
    CustomerContactPreferenceRequest,
    CustomerContactPreferenceResponse,
)


customers_router = APIRouter(
    prefix="/api/v1/customers",
    tags=["customers"],
)


@customers_router.patch(
    "/{customer_id}/contact-preferences",
    response_model=CustomerContactPreferenceResponse,
    summary="고객 마케팅 수신 거부 상태 변경",
)
def update_customer_contact_preferences(
    customer_id: int,
    payload: CustomerContactPreferenceRequest,
    _current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> CustomerContactPreferenceResponse:
    """법적 동의 데이터는 관리자만 변경할 수 있도록 제한합니다."""
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="The customer was not found.",
        )
    customer.marketing_opt_out = payload.marketing_opt_out
    db.commit()
    db.refresh(customer)
    return CustomerContactPreferenceResponse(
        customer_id=customer.customer_id,
        marketing_opt_out=customer.marketing_opt_out,
        last_contacted_at=customer.last_contacted_at,
    )
