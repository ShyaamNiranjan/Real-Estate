"""AI writing help (docs/SCOPE.md 8.4).

Only text goes to the provider: the listing's structured details, photo labels and the agent's
summary with emails, phone numbers and links removed. Never images, names, contact details or
anything about buyers. Output is checked (shape, lengths, fair-housing phrases), retried once, and
otherwise replaced by a template built from the details.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, BeforeValidator, Field, ValidationError
from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from app import sections
from app.ai_client import AiError, TextTap, Usage, cost_usd, parse_json, provider, stream_chat
from app.db import tenant_session
from app.deps import Auth, in_workspace
from app.errors import ApiError, ErrorResponse
from app.fair_housing import strings_in, violations
from app.listings import _editable, _float, _touch, build
from app.ratelimit import Rule, enforce

router = APIRouter(
    prefix="/api/v1/listings",
    tags=["ai"],
    responses={k: {"model": ErrorResponse} for k in (401, 403, 404, 409, 422, 429, 502)},
)

PROMPTS = Path(__file__).resolve().parent / "prompts"
LISTING_PROMPT, LISTING_PROMPT_VERSION = PROMPTS / "listing_v1.md", "listing-v1"
REWRITE_PROMPT, REWRITE_PROMPT_VERSION = PROMPTS / "rewrite_v1.md", "rewrite-v1"

MIN_SUMMARY_WORDS = 40
FULL_PER_LISTING_PER_DAY = 10
REWRITES_PER_LISTING_PER_DAY = 60
PER_WORKSPACE_PER_DAY = 300
AI_USER = Rule("ai-user", 60, 3600)
FALLBACK_MESSAGE = "We've started your page; you can refine it below."
DRAFTED_TYPES = ("story", "spaces", "location", "faq")
REWRITABLE = frozenset({"story", "spaces", "location", "faq", "cta", "quote"})
CAPTION_LABELS = ("Arrival", "Living", "Kitchen", "Dining", "Bedrooms", "Bathroom", "Outdoors", "The view")

Tone = Literal["luxury", "modern", "warm", "minimal"]
TONES: dict[str, str] = {
    "luxury": "refined and assured; elegant vocabulary, unhurried rhythm, never boastful.",
    "modern": "clean and confident; short sentences, design-aware, concrete.",
    "warm": "friendly and inviting; how the spaces feel day to day, still factual.",
    "minimal": "spare and precise; fewest words that carry the facts, no flourishes.",
}
Style = Literal["shorter", "luxurious", "factual"]
STYLES: dict[str, str] = {
    "shorter": "to be about half as long, keeping the most useful facts.",
    "luxurious": "to feel more refined and elegant, without exaggerating or adding facts.",
    "factual": "to be plain and factual: concrete details first, no adjectives the facts don't support.",
}
SPELLING = {"US": "American English", "CA": "Canadian English", "AU": "Australian English"}


# ---------- what the model must return ----------


def _clip(limit: int):
    return BeforeValidator(lambda v: (v if isinstance(v, str) else "" if v is None else str(v)).strip()[:limit])


def _first(limit: int):
    return BeforeValidator(lambda v: v[:limit] if isinstance(v, list) else [])


class DraftStory(BaseModel):
    heading: Annotated[str, _clip(120)] = ""
    body: Annotated[str, _clip(4000)] = ""


class DraftSpace(BaseModel):
    name: Annotated[str, _clip(60)]
    description: Annotated[str, _clip(600)] = ""


class DraftLocation(BaseModel):
    heading: Annotated[str, _clip(120)] = ""
    body: Annotated[str, _clip(4000)] = ""
    highlights: Annotated[list[Annotated[str, _clip(80)]], _first(8)] = []


class DraftQuestion(BaseModel):
    question: Annotated[str, _clip(200)]
    answer: Annotated[str, _clip(1000)]


class DraftCaption(BaseModel):
    label: Annotated[str, _clip(40)] = ""
    text: Annotated[str, _clip(200)] = ""


class DraftAlt(BaseModel):
    label: Annotated[str, _clip(60)]
    alt: Annotated[str, _clip(200)]


class Draft(BaseModel):
    hero_line: Annotated[str, _clip(160)] = ""
    story: DraftStory = DraftStory()
    spaces: Annotated[list[DraftSpace], _first(12)] = []
    location: DraftLocation = DraftLocation()
    faq: Annotated[list[DraftQuestion], _first(10)] = []
    captions: Annotated[list[DraftCaption], _first(20)] = []
    seo_title: Annotated[str, _clip(70)] = ""
    seo_description: Annotated[str, _clip(170)] = ""
    photo_alt: Annotated[list[DraftAlt], _first(40)] = []


# ---------- what the model is given ----------

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_PHONE_LIKE = re.compile(r"\+?\(?\d[\d\s().-]{6,}\d")


def scrub(value: str) -> str:
    """Removes contact details the agent may have typed into free text."""
    value = _EMAIL.sub("[removed]", value)
    value = _URL.sub("[removed]", value)
    return _PHONE_LIKE.sub(lambda m: "[removed]" if sum(c.isdigit() for c in m.group()) >= 9 else m.group(), value)


_number = sections._number


def facts_of(s: Session, listing: Row) -> dict:
    labels = list(s.execute(
        text("""SELECT DISTINCT label FROM media WHERE listing_id = :l AND kind IN ('gallery', 'hero')
                AND deleted_at IS NULL AND label <> '' ORDER BY label LIMIT 40"""),
        {"l": listing.id},
    ).scalars())
    captions = 0
    if listing.experience_type == "immersive":
        existing = s.execute(text("SELECT count(*) FROM walkthrough_beats WHERE listing_id = :l"),
                             {"l": listing.id}).scalar_one()
        captions = min(existing, 20) or 6
    price = listing.price_label.strip()
    if not price and listing.price_amount is not None:
        price = f"{listing.price_currency} {_number(_float(listing.price_amount))}"
    area = f"{_number(_float(listing.area))} {'sq ft' if listing.area_unit == 'sqft' else 'm²'}" if listing.area else ""
    facts = {
        "title": scrub(listing.title), "property_type": listing.property_type, "location": scrub(listing.location),
        "price": price, "bedrooms": listing.bedrooms,
        "bathrooms": _number(_float(listing.bathrooms)) if listing.bathrooms is not None else None,
        "area": area, "presentation": "video walkthrough" if listing.experience_type == "immersive" else "photos",
        "summary": scrub(listing.summary), "photo_labels": labels,
    }
    return {**{k: v for k, v in facts.items() if v not in (None, "", [])}, "caption_count": captions}


def _spelling(ws: Row) -> str:
    return SPELLING.get(ws.country_code or "", "British English")


# ---------- template (fallback, and the stand-in before a provider is configured) ----------


def _clip_sentence(value: str, limit: int) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    cut = value[:limit - 1].rsplit(" ", 1)[0]
    return f"{cut}…"


def template_draft(facts: dict) -> Draft:
    kind = (facts.get("property_type") or "home").lower()
    where = facts.get("location", "")
    beds = facts.get("bedrooms")
    hero = f"{beds}-bedroom {kind}" if beds else kind
    hero = (hero + (f" in {where}" if where else ""))
    title = facts.get("title") or hero
    summary = facts.get("summary", "")
    return Draft(
        hero_line=hero[:1].upper() + hero[1:],
        story=DraftStory(heading="The story", body=summary),
        spaces=[DraftSpace(name="[Add a room]", description="[Add what makes this space special]")],
        location=DraftLocation(heading="The location",
                               body=f"[Add what's nearby{' in ' + where if where else ''}: transport, shops, parks]"),
        captions=[DraftCaption(label=CAPTION_LABELS[i % len(CAPTION_LABELS)]) for i in range(facts["caption_count"])],
        seo_title=_clip_sentence(f"{title} | {where}" if where else title, 70),
        seo_description=_clip_sentence(summary, 155),
        photo_alt=[DraftAlt(label=label, alt=label) for label in facts.get("photo_labels", [])],
    )


def _stub_rewrite(content: dict, style: str) -> dict:
    if style != "shorter":
        return content

    def shorten(value):
        if isinstance(value, str) and len(value) > 80:
            parts = re.split(r"(?<=[.!?])\s+", value)
            return " ".join(parts[:max(1, len(parts) // 2)])
        if isinstance(value, list):
            return [shorten(v) for v in value]
        if isinstance(value, dict):
            return {k: shorten(v) for k, v in value.items()}
        return value

    return shorten(content)


# ---------- shared ----------


def _check_limits(s: Session, listing_id: UUID, kind: str, per_listing: int) -> None:
    row = s.execute(
        text("""SELECT count(*) FILTER (WHERE listing_id = :l AND kind = :k) AS listing, count(*) AS workspace
                FROM ai_generations WHERE created_at > now() - interval '1 day'"""),
        {"l": listing_id, "k": kind},
    ).one()
    if row.listing >= per_listing:
        what = "regenerated this listing" if kind == "full" else "rewritten sections of this listing"
        raise ApiError(429, "ai_limit", f"You've {what} {per_listing} times today. Try again tomorrow, or edit the text directly.")
    if row.workspace >= PER_WORKSPACE_PER_DAY:
        raise ApiError(429, "ai_limit", "Your workspace has used today's writing help. Try again tomorrow.")


def _start(s: Session, auth: Auth, listing_id: UUID, kind: str, prompt_version: str) -> UUID:
    generation_id, p = uuid4(), provider()
    s.execute(
        text("""INSERT INTO ai_generations (id, workspace_id, listing_id, user_id, kind, provider, model, prompt_version)
                VALUES (:id, :w, :l, :u, :k, :p, :m, :v)"""),
        {"id": generation_id, "w": auth.workspace_id, "l": listing_id, "u": auth.user_id, "k": kind,
         "p": p.name, "m": p.model, "v": prompt_version},
    )
    return generation_id


def _finish(s: Session, generation_id: UUID, status: str, attempts: int, usage: Usage, error: str) -> None:
    s.execute(
        text("""UPDATE ai_generations SET status = :st, attempts = :a, input_tokens = :i, output_tokens = :o,
                       cost_usd = :c, error = :e, finished_at = now() WHERE id = :id"""),
        {"st": status, "a": attempts, "i": usage.input_tokens, "o": usage.output_tokens,
         "c": round(cost_usd(usage), 6), "e": error[:300], "id": generation_id},
    )


def _add(total: Usage, part: Usage) -> None:
    total.input_tokens += part.input_tokens
    total.output_tokens += part.output_tokens


def _text_beyond_headings(content: dict) -> bool:
    return any(s.strip() for s in strings_in({k: v for k, v in content.items() if k != "heading"}))


# ---------- full generation ----------


class GenerateIn(BaseModel):
    tone: Tone = "modern"
    replace_edits: bool = Field(default=False, description="Send true after the user confirms replacing their own edits.")


def _apply(s: Session, listing: Row, draft: Draft, tone: str) -> None:
    rows = s.execute(text("SELECT id, type, content FROM listing_sections WHERE listing_id = :l ORDER BY sort_order"),
                     {"l": listing.id}).all()
    first: dict[str, Row] = {}
    for r in rows:
        first.setdefault(r.type, r)

    def heading(kind: str, proposed: str = "") -> str:
        return proposed or (first[kind].content or {}).get("heading", "")

    contents = {
        "story": {"heading": heading("story", draft.story.heading) if "story" in first else "", "body": draft.story.body},
        "spaces": {"heading": heading("spaces") if "spaces" in first else "",
                   "items": [i.model_dump() for i in draft.spaces if i.name]},
        "location": {"heading": heading("location", draft.location.heading) if "location" in first else "",
                     "body": draft.location.body, "highlights": [h for h in draft.location.highlights if h]},
        "faq": {"heading": heading("faq") if "faq" in first else "",
                "items": [i.model_dump() for i in draft.faq if i.question and i.answer]},
    }
    for kind, content in contents.items():
        if kind in first:
            s.execute(
                text("""UPDATE listing_sections SET content = CAST(:c AS jsonb), ai_drafted = true, updated_at = now()
                        WHERE id = :id"""),
                {"c": json.dumps(sections.validate(kind, content)), "id": first[kind].id},
            )

    s.execute(
        text("""UPDATE listings SET subtitle = :sub, seo_title = :t, seo_description = :d, ai_tone = :tone
                WHERE id = :id"""),
        {"sub": draft.hero_line, "t": draft.seo_title, "d": draft.seo_description, "tone": tone, "id": listing.id},
    )

    if listing.experience_type == "immersive" and draft.captions:
        beats = s.execute(text("SELECT id FROM walkthrough_beats WHERE listing_id = :l ORDER BY at"),
                          {"l": listing.id}).scalars().all()
        if beats:
            for beat_id, caption in zip(beats, draft.captions, strict=False):
                s.execute(text("UPDATE walkthrough_beats SET label = :label, text = :text WHERE id = :id"),
                          {"label": caption.label, "text": caption.text, "id": beat_id})
        else:
            count = len(draft.captions)
            for i, caption in enumerate(draft.captions):
                s.execute(
                    text("""INSERT INTO walkthrough_beats (workspace_id, listing_id, at, label, text)
                            VALUES (:w, :l, :at, :label, :text)"""),
                    {"w": listing.workspace_id, "l": listing.id, "at": round((i + 1) / (count + 1), 4),
                     "label": caption.label, "text": caption.text},
                )

    for photo in draft.photo_alt:
        s.execute(
            text("""UPDATE media SET alt = :alt WHERE listing_id = :l AND lower(label) = lower(:label) AND alt = ''
                    AND kind IN ('gallery', 'hero') AND deleted_at IS NULL"""),
            {"alt": photo.alt, "label": photo.label, "l": listing.id},
        )
    _touch(s, listing.id)


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def _attempt_draft(system: str, user: str, facts: dict, usage: Usage) -> Iterator[str | Draft]:
    """Streams display text; the last item is the validated Draft. Raises AiError on a bad reply."""
    tap, parts = TextTap(), []
    for chunk in stream_chat(system, user, usage, stub=lambda: template_draft(facts).model_dump_json()):
        parts.append(chunk)
        shown = tap.feed(chunk)
        if shown:
            yield shown
    try:
        draft = Draft.model_validate(parse_json("".join(parts)))
    except ValidationError:
        raise AiError("reply didn't match the section format") from None
    found = violations(*strings_in(draft.model_dump()))
    if found:
        raise AiError(f"fair-housing phrase: {found[0]}")
    yield draft


def _generate_stream(auth: Auth, listing_id: UUID, generation_id: UUID, system: str, user: str,
                     facts: dict, local_facts: dict, tone: str) -> Iterator[str]:
    yield _event("stage", {"stage": "writing"})
    total, draft, error, attempts = Usage(), None, "", 0
    for attempt in (1, 2):
        attempts = attempt
        if attempt == 2:
            yield _event("stage", {"stage": "retrying"})
        usage = Usage()
        try:
            for item in _attempt_draft(system, user, facts, usage):
                if isinstance(item, Draft):
                    draft = item
                else:
                    yield _event("text", {"text": item})
        except AiError as exc:
            error = str(exc)
        _add(total, usage)
        if draft is not None:
            break

    yield _event("stage", {"stage": "building"})
    fallback = draft is None
    if fallback:
        draft = template_draft(local_facts)
    try:
        with tenant_session(auth.user_id, auth.workspace_id) as s:
            access, _, listing = _editable(s, auth, listing_id)
            _apply(s, listing, draft, tone)
            _finish(s, generation_id, "fallback" if fallback else "ok", attempts, total, error)
            out = build(s, listing_id, access)
    except ApiError as exc:
        with tenant_session(auth.user_id, auth.workspace_id) as s:
            _finish(s, generation_id, "failed", attempts, total, exc.message)
        yield _event("error", {"code": exc.code, "message": exc.message})
        return
    yield _event("done", {"fallback": fallback, "message": FALLBACK_MESSAGE if fallback else None,
                          "listing": out.model_dump(mode="json")})


STREAM_DOC = (
    "Server-sent events (read with fetch + a stream reader; it's a POST). In order: "
    "`stage {stage: writing}`, many `text {text}` (append to the live preview), optionally "
    "`stage {stage: retrying}` (clear the preview), `stage {stage: building}`, then `done {fallback, message, "
    "listing}` with the full listing, or `error {code, message}`."
)


@router.post(
    "/{listing_id}/ai/generate",
    response_class=StreamingResponse,
    responses={200: {"description": STREAM_DOC, "content": {"text/event-stream": {"schema": {"type": "string"}}}}},
)
def generate(listing_id: UUID, body: GenerateIn, auth: Auth = Depends(in_workspace)) -> StreamingResponse:
    """Writes the listing's sections, captions, SEO text and photo descriptions from the summary and details."""
    enforce((AI_USER, str(auth.user_id)))
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _, ws, listing = _editable(s, auth, listing_id)
        if len(listing.summary.split()) < MIN_SUMMARY_WORDS:
            raise ApiError(422, "summary_too_short",
                           f"Tell us a little more about this home (at least {MIN_SUMMARY_WORDS} words).")
        _check_limits(s, listing_id, "full", FULL_PER_LISTING_PER_DAY)
        if not body.replace_edits:
            drafted = s.execute(
                text("SELECT content FROM listing_sections WHERE listing_id = :l AND type = ANY(:t) AND NOT ai_drafted"),
                {"l": listing_id, "t": list(DRAFTED_TYPES)},
            ).scalars().all()
            if any(_text_beyond_headings(c or {}) for c in drafted):
                raise ApiError(409, "confirm_replace", "This replaces text you've written yourself. Continue?")
        facts = facts_of(s, listing)
        local_facts = {**facts, "summary": listing.summary, "title": listing.title, "location": listing.location}
        system = LISTING_PROMPT.read_text(encoding="utf-8").format(
            tone_guide=TONES[body.tone], spelling=_spelling(ws), caption_count=facts["caption_count"])
        generation_id = _start(s, auth, listing_id, "full", LISTING_PROMPT_VERSION)
    user = json.dumps({k: v for k, v in facts.items() if k != "caption_count"}, ensure_ascii=False)
    return StreamingResponse(
        _generate_stream(auth, listing_id, generation_id, system, user, facts, local_facts, body.tone),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- per-section rewrite ----------


class RewriteIn(BaseModel):
    section_id: UUID
    style: Style


class RewriteOut(BaseModel):
    section_id: UUID
    type: str
    content: dict = Field(description="A proposal only. Save it with PATCH /listings/{id}/sections/{sid} if the user keeps it.")


@router.post("/{listing_id}/ai/rewrite", response_model=RewriteOut)
def rewrite(listing_id: UUID, body: RewriteIn, auth: Auth = Depends(in_workspace)) -> RewriteOut:
    enforce((AI_USER, str(auth.user_id)))
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _, ws, listing = _editable(s, auth, listing_id)
        section = s.execute(text("SELECT type, content FROM listing_sections WHERE id = :id AND listing_id = :l"),
                            {"id": body.section_id, "l": listing_id}).first()
        if section is None:
            raise ApiError(404, "not_found", "That section doesn't exist.")
        if section.type not in REWRITABLE:
            raise ApiError(422, "not_rewritable", "This section can't be rewritten.")
        current = dict(section.content or {})
        if not _text_beyond_headings(current):
            raise ApiError(422, "nothing_to_rewrite", "Add some text to this section first.")
        _check_limits(s, listing_id, "rewrite_section", REWRITES_PER_LISTING_PER_DAY)
        facts = facts_of(s, listing)
        system = REWRITE_PROMPT.read_text(encoding="utf-8").format(style_guide=STYLES[body.style],
                                                                   spelling=_spelling(ws))
        generation_id = _start(s, auth, listing_id, "rewrite_section", REWRITE_PROMPT_VERSION)

    fields = sections.LIBRARY[section.type][0].model_fields
    sent = {k: (scrub(v) if isinstance(v, str) else v) for k, v in current.items()}
    user = json.dumps({"facts": {k: v for k, v in facts.items() if k != "caption_count"},
                       "section_type": section.type, "current_content": sent}, ensure_ascii=False)
    total, result, error, attempts = Usage(), None, "", 0
    for attempt in (1, 2):
        attempts, usage = attempt, Usage()
        try:
            reply = "".join(stream_chat(system, user, usage, stub=lambda: json.dumps(_stub_rewrite(current, body.style))))
            proposed = sections.validate(section.type, {k: v for k, v in parse_json(reply).items() if k in fields})
            found = violations(*strings_in(proposed))
            if found:
                raise AiError(f"fair-housing phrase: {found[0]}")
            result = proposed
        except (AiError, ValueError) as exc:
            error = str(exc).splitlines()[0]
        _add(total, usage)
        if result is not None:
            break
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        _finish(s, generation_id, "ok" if result is not None else "failed", attempts, total, error)
    if result is None:
        raise ApiError(502, "ai_unavailable", "We couldn't rewrite this right now. Try again in a minute.")
    return RewriteOut(section_id=body.section_id, type=section.type, content=result)
