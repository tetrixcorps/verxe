from typing import Optional, List
from pydantic import BaseModel, UUID4, condecimal
from datetime import datetime
from decimal import Decimal

# Token Balance Schema
class TokenBalance(BaseModel):
    user_id: UUID4
    amount: condecimal(max_digits=18, decimal_places=2)
    updated_at: datetime
    
    class Config:
        orm_mode = True

# Token Transaction Base Schema
class TokenTransactionBase(BaseModel):
    amount: condecimal(max_digits=18, decimal_places=2)
    type: str
    description: Optional[str] = None
    reference_id: Optional[UUID4] = None

# Create Token Transaction Schema
class TokenTransactionCreate(TokenTransactionBase):
    pass

# Token Transaction Response Schema
class TokenTransaction(TokenTransactionBase):
    id: UUID4
    user_id: UUID4
    created_at: datetime
    
    class Config:
        orm_mode = True

# Token Balance Update Schema
class TokenBalanceUpdate(BaseModel):
    amount: condecimal(max_digits=18, decimal_places=2) 