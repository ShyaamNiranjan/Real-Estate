"""Country compliance profiles (docs/SCOPE.md 8.13). Publishing is blocked until every field
marked required for the workspace's profile is filled."""

from typing import Literal

from pydantic import BaseModel

Scope = Literal["workspace", "listing"]


class Field(BaseModel):
    key: str
    label: str
    scope: Scope
    required: bool
    hint: str = ""


class Profile(BaseModel):
    key: str
    name: str
    currency: str
    area_unit: Literal["sqft", "sqm"]
    fields: list[Field]
    automatic: list[str] = []


def _f(key: str, label: str, scope: Scope, required: bool, hint: str = "") -> Field:
    return Field(key=key, label=label, scope=scope, required=required, hint=hint)


PROFILES: dict[str, Profile] = {p.key: p for p in [
    Profile(key="US", name="United States", currency="USD", area_unit="sqft",
            automatic=["Equal Housing Opportunity logo"], fields=[
        _f("licence_number", "Real estate licence number", "workspace", True),
        _f("licence_state", "Licensing state", "workspace", True, "For example: California"),
        _f("brokerage_name", "Brokerage", "workspace", True, "The brokerage you're licensed under"),
    ]),
    Profile(key="GB", name="United Kingdom", currency="GBP", area_unit="sqft", fields=[
        _f("redress_scheme", "Redress scheme", "workspace", True, "For example: The Property Ombudsman"),
        _f("redress_membership_number", "Redress scheme membership number", "workspace", True),
        _f("tenure", "Tenure", "listing", True, "Freehold, leasehold or share of freehold"),
        _f("council_tax_band", "Council tax band", "listing", True),
    ]),
    Profile(key="AE", name="United Arab Emirates", currency="AED", area_unit="sqft", fields=[
        _f("broker_registration_number", "Broker registration number (BRN)", "workspace", True),
        _f("permit_number", "Advertising permit number", "listing", True, "Trakheesi / DLD permit for this listing"),
    ]),
    Profile(key="IN", name="India", currency="INR", area_unit="sqft", fields=[
        _f("rera_agent_number", "RERA agent registration number", "workspace", True),
        _f("rera_project_number", "RERA project registration number", "listing", False),
    ]),
    Profile(key="CA", name="Canada", currency="CAD", area_unit="sqft", fields=[
        _f("licence_number", "Licence or registration number", "workspace", True),
        _f("brokerage_name", "Brokerage", "workspace", True),
    ]),
    Profile(key="AU", name="Australia", currency="AUD", area_unit="sqm", fields=[
        _f("licence_number", "Licence number", "workspace", True),
        _f("brokerage_name", "Agency", "workspace", True),
    ]),
    Profile(key="EU", name="European Union", currency="EUR", area_unit="sqm", fields=[
        _f("agent_registration_number", "Agent registration number", "workspace", False),
        _f("energy_rating", "Energy rating (EPC / energy label)", "listing", True),
    ]),
    Profile(key="OTHER", name="Another country", currency="USD", area_unit="sqm", fields=[
        _f("disclosure", "Licence or registration details", "workspace", False,
           "Anything your local rules require you to show"),
    ]),
]}

EU_COUNTRIES = frozenset(
    "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
)


def profile_for_country(country_code: str) -> Profile:
    code = country_code.upper()
    if code in PROFILES and code not in ("EU", "OTHER"):
        return PROFILES[code]
    if code in EU_COUNTRIES:
        return PROFILES["EU"]
    return PROFILES["OTHER"]


def workspace_fields(profile_key: str | None) -> list[Field]:
    if not profile_key:
        return []
    return [f for f in PROFILES[profile_key].fields if f.scope == "workspace"]


def missing_workspace_fields(profile_key: str | None, values: dict[str, str]) -> list[Field]:
    return [f for f in workspace_fields(profile_key) if f.required and not str(values.get(f.key, "")).strip()]
