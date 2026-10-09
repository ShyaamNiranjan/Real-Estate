"""Listing section library (docs/SCOPE.md 8.5). Agents edit text inside fixed, designed
sections; they never position anything freely. Content is validated per section type."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Content(BaseModel):
    model_config = ConfigDict(extra="forbid")


Short = Field(default="", max_length=120)
Body = Field(default="", max_length=4000)


class Story(_Content):
    heading: str = Short
    body: str = Body


class GlanceItem(_Content):
    label: str = Field(max_length=30)
    value: str = Field(max_length=40)


class AtAGlance(_Content):
    heading: str = Short
    auto: bool = True
    items: list[GlanceItem] = Field(default_factory=list, max_length=6)


class Space(_Content):
    name: str = Field(max_length=60)
    description: str = Field(default="", max_length=600)


class Spaces(_Content):
    heading: str = Short
    items: list[Space] = Field(default_factory=list, max_length=12)


class Location(_Content):
    heading: str = Short
    body: str = Body
    highlights: list[str] = Field(default_factory=list, max_length=8)


class Question(_Content):
    question: str = Field(max_length=200)
    answer: str = Field(max_length=1000)


class Faq(_Content):
    heading: str = Short
    items: list[Question] = Field(default_factory=list, max_length=10)


class Quote(_Content):
    text: str = Field(default="", max_length=400)
    attribution: str = Field(default="", max_length=80)


class Cta(_Content):
    heading: str = Short
    body: str = Field(default="", max_length=400)
    button_label: str = Field(default="", max_length=30)


class Gallery(_Content):
    heading: str = Short


class FloorPlans(_Content):
    heading: str = Short


SectionType = Literal["story", "at_a_glance", "spaces", "location", "faq", "quote", "cta", "gallery", "floor_plans"]

LIBRARY: dict[str, tuple[type[_Content], tuple[str, ...]]] = {
    "story": (Story, ("split", "centered", "editorial")),
    "at_a_glance": (AtAGlance, ("tiles", "row")),
    "spaces": (Spaces, ("cards", "list", "alternating")),
    "location": (Location, ("split", "full")),
    "faq": (Faq, ("accordion", "columns")),
    "quote": (Quote, ("large", "minimal")),
    "cta": (Cta, ("banner", "card")),
    "gallery": (Gallery, ("strip", "grid")),
    "floor_plans": (FloorPlans, ("tabs",)),
}

DEFAULT_SET: tuple[tuple[str, dict], ...] = (
    ("story", {"heading": "The story"}),
    ("at_a_glance", {"heading": "At a glance"}),
    ("spaces", {"heading": "The spaces"}),
    ("gallery", {"heading": "Gallery"}),
    ("floor_plans", {"heading": "Floor plans"}),
    ("location", {"heading": "The location"}),
    ("faq", {"heading": "Questions"}),
    ("cta", {"heading": "Arrange a viewing", "button_label": "Enquire"}),
)


def validate(section_type: str, content: dict) -> dict:
    model, _ = LIBRARY[section_type]
    return model.model_validate(content).model_dump()


def default_variant(section_type: str) -> str:
    return LIBRARY[section_type][1][0]


def variants(section_type: str) -> tuple[str, ...]:
    return LIBRARY[section_type][1]


def _number(value) -> str:
    text = f"{value:,.1f}" if value is not None else ""
    return text[:-2] if text.endswith(".0") else text


def glance_items(listing) -> list[dict]:
    """Auto-filled 'At a glance' boxes from the listing details (Bedrooms, Bathrooms, Area,
    Experience); empty values are left out."""
    unit = "sq ft" if listing.area_unit == "sqft" else "m²"
    items = []
    if listing.bedrooms is not None:
        items.append({"label": "Bedrooms", "value": _number(listing.bedrooms)})
    if listing.bathrooms is not None:
        items.append({"label": "Bathrooms", "value": _number(listing.bathrooms)})
    if listing.area is not None:
        items.append({"label": "Area", "value": f"{_number(listing.area)} {unit}"})
    items.append({"label": "Experience", "value": "Walkthrough" if listing.experience_type == "immersive" else "Photo tour"})
    return items
