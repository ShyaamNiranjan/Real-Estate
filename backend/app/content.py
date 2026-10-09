"""Shapes of published content (listing and site snapshots).

Every public response is passed through these models, so only the fields listed here can ever
reach a public page, whatever else ends up in a snapshot.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ComplianceItem(BaseModel):
    key: str
    label: str
    value: str


class Contact(BaseModel):
    email: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    booking_url: str | None = None


class Brand(BaseModel):
    display_name: str = ""
    brokerage_name: str = ""
    style_preset: str = "noir"
    compliance: list[ComplianceItem] = []


class Agent(BaseModel):
    name: str = ""
    licence_number: str = ""


class Image(BaseModel):
    id: UUID
    url: str
    thumb_url: str
    width: int | None
    height: int | None
    label: str = ""
    alt: str = ""


class FrameSet(BaseModel):
    """Live pages give a `pattern` (replace `{n}` with 0001…); draft previews give signed `urls`."""
    pattern: str | None = None
    urls: list[str] | None = None
    width: int
    height: int


class Walkthrough(BaseModel):
    count: int
    large: FrameSet
    small: FrameSet


class Hero(BaseModel):
    enabled: bool = True
    show_facts: bool = True
    show_price: bool = True
    image: Image | None = None


class Section(BaseModel):
    id: UUID
    type: str
    layout_variant: str
    content: dict


class Beat(BaseModel):
    at: float
    label: str
    text: str


class ListingContent(BaseModel):
    title: str
    subtitle: str = ""
    location: str = ""
    price_amount: float | None = None
    price_currency: str = "USD"
    price_label: str = ""
    bedrooms: int | None = None
    bathrooms: float | None = None
    area: float | None = None
    area_unit: str = "sqft"
    property_type: str = ""
    experience_type: Literal["photo", "immersive"] = "immersive"
    mobile_mode: str = "rotate"
    compliance: list[ComplianceItem] = []
    seo_title: str = ""
    seo_description: str = ""
    sections: list[Section] = []
    hero: Hero = Hero()
    beats: list[Beat] = []
    gallery: list[Image] = []
    floor_plans: list[Image] = []
    walkthrough: dict[Literal["landscape", "portrait"], Walkthrough] = {}
    agent: Agent = Agent()
    contact: Contact = Contact()
    brand: Brand = Brand()


class SiteContent(BaseModel):
    display_name: str
    brokerage_name: str = ""
    tagline: str = ""
    bio: str = ""
    photo_url: str | None = None
    style_preset: str = "noir"
    country_code: str | None = None
    contact: Contact = Contact()
    compliance: list[ComplianceItem] = []
    featured_listing_ids: list[UUID] = []


class ListingCard(BaseModel):
    id: UUID
    path: str
    status: Literal["published", "sold"]
    title: str
    location: str
    price_amount: float | None
    price_currency: str
    price_label: str
    bedrooms: int | None
    bathrooms: float | None
    area: float | None
    area_unit: str
    property_type: str
    experience_type: str
    image: Image | None
    published_at: datetime | None
