import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from src.models.source_item import Base


class ProductCandidate(Base):
    __tablename__ = "product_candidates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    slug = Column(String(128), nullable=False, unique=True, index=True)
    name = Column(String(256), nullable=False)
    homepage_url = Column(Text, nullable=False, unique=True)
    tagline = Column(Text, nullable=True)

    discovered_from = Column(String(64), nullable=False, index=True)
    discovered_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    last_experienced_at = Column(DateTime(timezone=True), nullable=True)
    experience_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
