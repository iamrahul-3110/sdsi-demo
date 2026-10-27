"""Room domain model and Pydantic schemas."""

from typing import List, Optional
from pydantic import BaseModel, Field


class Room(BaseModel):
    """A meeting room available for booking."""
    id: str = Field(..., description="Unique room identifier")
    name: str = Field(..., description="Human-readable room name")
    capacity: int = Field(..., ge=1, description="Maximum number of occupants")
    floor: int = Field(..., description="Floor number (0 = ground)")
    amenities: List[str] = Field(default_factory=list, description="Room features")
    description: Optional[str] = Field(None, description="Optional room description")


class RoomCreate(BaseModel):
    """Schema for creating a new room (optional administrative use)."""
    id: str = Field(..., pattern=r"^room-\d{3,}$")
    name: str = Field(..., min_length=1, max_length=100)
    capacity: int = Field(..., ge=1)
    floor: int
    amenities: List[str] = Field(default_factory=list)
    description: Optional[str] = None