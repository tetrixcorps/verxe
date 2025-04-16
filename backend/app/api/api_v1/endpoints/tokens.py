from typing import List, Dict, Any
from uuid import UUID
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Request
import stripe

from ....core.deps import get_current_user, get_db, get_current_active_user
from ....models.user import User
from ....schemas.token import TokenBalance, TokenTransaction, TokenBalanceUpdate, TokenTransactionCreate
from ....services.token_service import TokenService
from ....core.config import settings

# Configure Stripe (should be done securely, e.g., via env vars)
stripe.api_key = settings.STRIPE_SECRET_KEY

router = APIRouter()

@router.get("/balance", response_model=TokenBalance)
async def get_balance(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the current user's token balance.
    """
    token_service = TokenService(db)
    return await token_service.get_user_balance(current_user.id)

@router.get("/transactions", response_model=List[TokenTransaction])
async def get_transactions(
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the current user's token transaction history.
    """
    token_service = TokenService(db)
    return await token_service.get_user_transactions(current_user.id, limit, offset)

@router.post("/transfer", response_model=TokenTransaction)
async def transfer_tokens(
    recipient_id: UUID,
    amount: Decimal,
    description: str = "Token transfer",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Transfer tokens to another user.
    """
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    
    if current_user.id == recipient_id:
        raise HTTPException(status_code=400, detail="Cannot transfer tokens to yourself")
    
    token_service = TokenService(db)
    try:
        sender_tx, _ = await token_service.transfer_tokens(
            current_user.id,
            recipient_id,
            amount,
            "transfer",
            description
        )
        return sender_tx
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/tip", response_model=TokenTransaction)
async def tip_user(
    recipient_id: UUID,
    amount: Decimal,
    stream_id: UUID = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Tip another user tokens, optionally in context of a stream.
    """
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Tip amount must be positive")
    
    if current_user.id == recipient_id:
        raise HTTPException(status_code=400, detail="Cannot tip yourself")
    
    token_service = TokenService(db)
    try:
        description = "Tip"
        if stream_id:
            description = f"Tip for stream {stream_id}"
        
        sender_tx, _ = await token_service.transfer_tokens(
            current_user.id,
            recipient_id,
            amount,
            "tip",
            description,
            stream_id
        )
        return sender_tx
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- Stripe Integration Endpoints --- 

class PurchaseRequest(BaseModel):
    amount_usd: float
    token_package: str

@router.post("/purchase/intent", response_model=Dict[str, str])
async def create_purchase_intent(
    purchase_request: PurchaseRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a Stripe PaymentIntent to purchase tokens.
    Returns the client_secret needed by the frontend.
    """
    # TODO: Add validation - check if token_package is valid and amount_usd matches
    # TODO: Calculate token amount based on package/amount_usd
    
    try:
        # Convert amount to cents
        amount_cents = int(purchase_request.amount_usd * 100)
        
        payment_intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            metadata={
                'user_id': str(current_user.id),
                'token_package': purchase_request.token_package
                # Add other relevant metadata
            }
        )
        return {"client_secret": payment_intent.client_secret}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Stripe error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal server error: {str(e)}")

@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle incoming webhooks from Stripe.
    """
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    # Assuming STRIPE_WEBHOOK_SECRET is in settings
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET 
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        # Invalid payload
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    # Handle the event
    if event['type'] == 'payment_intent.succeeded':
        payment_intent = event['data']['object']
        metadata = payment_intent.get('metadata', {})
        user_id_str = metadata.get('user_id')
        token_package = metadata.get('token_package')
        amount_received = payment_intent['amount_received'] # Amount in cents

        if user_id_str and token_package:
            # TODO: Determine token amount based on token_package or amount_received
            token_amount = Decimal(str(amount_received / 10)) # Example: 10 cents = 1 token
            user_id = UUID(user_id_str)
            
            token_service = TokenService(db)
            try:
                await token_service.add_tokens(
                    user_id=user_id,
                    amount=token_amount,
                    type="purchase",
                    description=f"Purchase of {token_package} package",
                    reference_id=payment_intent.id # Use PaymentIntent ID as reference
                )
                print(f"Successfully granted {token_amount} tokens to user {user_id}")
            except Exception as e:
                print(f"Error granting tokens after successful payment: {str(e)}")
                # TODO: Implement retry or alerting mechanism
        else:
            print("Webhook Error: Missing user_id or token_package in metadata")

    # ... handle other event types if needed

    return {"status": "success"} 