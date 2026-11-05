"""AI care-gap suggestions.

Retrieves species care guidelines (a small curated knowledge base), deterministically detects
which guideline categories a pet's existing tasks don't cover, then asks an LLM to draft a
concrete Task for each gap, grounded in the retrieved guideline text. Every draft is validated
by constructing a real pawpal_system.Task (reusing its own validation, never duplicating it);
an invalid draft is fed back to the model and retried a bounded number of times before being
dropped. Nothing here ever mutates a Pet's tasks -- callers decide whether to add a draft.
"""

import json
import logging
from dataclasses import dataclass, replace
from datetime import date, time
from typing import Dict, Iterable, List, Optional, Protocol, Tuple

from pawpal_system import Frequency, Owner, Pet, Priority, Task

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CareCategory:
    key: str
    keywords: Tuple[str, ...]  # lowercase substrings matched against Task.name
    guideline_text: str  # the one fact the LLM is grounded on
    suggested_duration: int
    suggested_priority: Priority
    suggested_frequency: Frequency
    suggested_start_time: time


CARE_GUIDELINES: Dict[str, List[CareCategory]] = {
    "dog": [
        CareCategory(
            "walk", ("walk", "hike"),
            "Dogs should get a daily walk of about 20-30 minutes.",
            25, Priority.HIGH, Frequency.DAILY, time(7, 30),
        ),
        CareCategory(
            "feeding", ("feed", "meal", "breakfast", "dinner", "food"),
            "Dogs are typically fed two meals a day, morning and evening.",
            10, Priority.HIGH, Frequency.DAILY, time(8, 0),
        ),
        CareCategory(
            "vet_checkup", ("vet", "checkup", "check-up"),
            "Dogs should have a vet checkup roughly every 6-12 months.",
            30, Priority.MEDIUM, Frequency.ONCE, time(10, 0),
        ),
        CareCategory(
            "grooming", ("bath", "shower", "groom"),
            "Dogs typically need a bath or grooming session every 4-6 weeks.",
            30, Priority.MEDIUM, Frequency.WEEKLY, time(16, 0),
        ),
    ],
    "cat": [
        CareCategory(
            "litter", ("litter", "box"),
            "A cat's litter box should be cleaned at least once a day.",
            10, Priority.HIGH, Frequency.DAILY, time(9, 0),
        ),
        CareCategory(
            "play", ("play", "toy"),
            "Cats benefit from at least one daily play session to stay active.",
            15, Priority.MEDIUM, Frequency.DAILY, time(18, 0),
        ),
        CareCategory(
            "vet_checkup", ("vet", "checkup", "check-up"),
            "Cats should have a vet checkup about once a year.",
            30, Priority.MEDIUM, Frequency.ONCE, time(10, 0),
        ),
        CareCategory(
            "grooming", ("bath", "shower", "groom", "brush"),
            "Cats usually benefit from regular brushing and occasional bathing.",
            20, Priority.LOW, Frequency.WEEKLY, time(16, 0),
        ),
    ],
    "_default": [
        CareCategory(
            "feeding", ("feed", "meal", "food"),
            "Most pets need at least one scheduled feeding each day.",
            10, Priority.HIGH, Frequency.DAILY, time(8, 0),
        ),
        CareCategory(
            "exercise", ("walk", "play", "exercise", "enrichment"),
            "Most pets benefit from some daily exercise or enrichment time.",
            15, Priority.MEDIUM, Frequency.DAILY, time(17, 0),
        ),
        CareCategory(
            "vet_checkup", ("vet", "checkup", "check-up"),
            "Most pets should see a vet for a checkup at least once a year.",
            30, Priority.MEDIUM, Frequency.ONCE, time(10, 0),
        ),
        CareCategory(
            "grooming", ("bath", "shower", "groom", "brush"),
            "Many pets benefit from occasional bathing or grooming.",
            20, Priority.LOW, Frequency.WEEKLY, time(16, 0),
        ),
    ],
}


def get_guidelines(species: str) -> List[CareCategory]:
    """Return the care categories for species (case-insensitive exact match), or the generic
    fallback for any species not in the seeded corpus (Pet.species is free text)."""
    return CARE_GUIDELINES.get(species.strip().lower(), CARE_GUIDELINES["_default"])


def detect_gaps(pet: Pet) -> List[CareCategory]:
    """Return care categories from this pet's species guidelines with no matching existing task.

    A category is "covered" if any of the pet's tasks -- completed or not, since a completed
    daily/weekly task still represents ongoing coverage because it regenerates via
    Task.next_occurrence -- has a name containing one of the category's keywords,
    case-insensitively. Deterministic; no I/O, no AI.
    """
    names = [t.name.lower() for t in pet.tasks]
    return [
        category
        for category in get_guidelines(pet.species)
        if not any(keyword in name for keyword in category.keywords for name in names)
    ]


class ClaudeClient(Protocol):
    def generate(self, prompt: str) -> str:
        ...


DEFAULT_MODEL = "claude-haiku-4-5-20251001"  # short structured-draft task; no need for a bigger model


class AnthropicClaudeClient:
    """Thin wrapper around the Anthropic SDK. anthropic is imported lazily so importing
    care_ai, or running its deterministic functions, never requires the package or an API key."""

    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)  # falls back to ANTHROPIC_API_KEY
        self._model = model

    def generate(self, prompt: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return next((block.text for block in response.content if block.type == "text"), "")


@dataclass
class SuggestionDraft:
    pet_name: str
    category_key: str
    task: Task  # already constructed via Task(...), so already validated
    reason: str


def _format_existing_tasks(pet: Pet) -> str:
    if not pet.tasks:
        return "(no tasks yet)"
    return ", ".join(f"{t.name} ({t.start_time:%H:%M}-{t.end_time():%H:%M})" for t in pet.tasks)


def _build_prompt(
    category: CareCategory, pet: Pet, owner: Owner, previous_error: Optional[str] = None
) -> str:
    prompt = f"""You are drafting ONE suggested pet-care task for a pet-care scheduling app.

Pet: {pet.name} (species: {pet.species})
Owner's available window: {owner.window_start:%H:%M}-{owner.window_end:%H:%M}
{pet.name}'s existing tasks: {_format_existing_tasks(pet)}

Care guideline to follow (the only fact you may rely on): "{category.guideline_text}"

{pet.name} currently has no task covering this guideline. Draft one task that fills this gap.
Try to pick a start time inside the owner's window that does not obviously overlap an existing
task, but exact conflict-free placement is not required -- the app resolves real conflicts later.

Respond with ONLY a single JSON object (no markdown fences, no extra text) with these keys:
- "name": short task title (string)
- "start_time": "HH:MM" 24-hour time (string)
- "duration_minutes": positive integer
- "priority": one of "LOW", "MEDIUM", "HIGH"
- "frequency": one of "once", "daily", "weekly"
- "reason": one plain-English sentence citing the guideline above, no invented facts
"""
    if previous_error:
        prompt += (
            f"\nYour previous attempt was invalid: {previous_error}\n"
            "Fix it and respond again with only the corrected JSON object.\n"
        )
    return prompt


def _parse_time(value: str) -> time:
    hour, minute = value.strip().split(":")
    return time(int(hour), int(minute))


def _parse_response(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"response was not valid JSON: {e}") from e
    required = ("name", "start_time", "duration_minutes", "priority", "frequency", "reason")
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"response JSON missing keys: {', '.join(missing)}")
    return data


def draft_suggestion(
    client: ClaudeClient,
    pet: Pet,
    owner: Owner,
    category: CareCategory,
    max_attempts: int = 3,
) -> Optional[SuggestionDraft]:
    """Ask client for a draft Task grounded in category.guideline_text; validate by constructing
    a real Task(...). On a malformed response or a Task.__post_init__ rejection, feed that exact
    error back into the next prompt and retry, up to max_attempts total calls. Never raises --
    returns None if every attempt fails.
    """
    error: Optional[str] = None
    for attempt in range(max_attempts):
        prompt = _build_prompt(category, pet, owner, previous_error=error)
        try:
            data = _parse_response(client.generate(prompt))
            task = Task(
                str(data["name"]),
                _parse_time(str(data["start_time"])),
                int(data["duration_minutes"]),
                Priority[str(data["priority"]).upper()],
                Frequency(str(data["frequency"]).lower()),
            )
            return SuggestionDraft(pet.name, category.key, task, str(data["reason"]))
        except Exception as e:
            # Broad on purpose: a malformed response (ValueError/KeyError/TypeError) and a
            # client-side failure (network error, API error, rate limit) must both be retried
            # or given up on the same way -- a suggestion is never worth crashing the page over.
            error = str(e)
            logger.warning(
                "care_ai: attempt %d/%d for %s/%s failed: %s",
                attempt + 1, max_attempts, pet.name, category.key, error,
            )
    return None


def _deconflict_drafts(drafts: List[SuggestionDraft], pet: Pet) -> List[SuggestionDraft]:
    """Nudge each draft's start time past any task it collides with today -- an existing task
    on the pet, or an earlier draft in this same batch -- reusing Task.overlaps so the rule
    matches the scheduler's own. Each category is drafted via an independent LLM call with no
    visibility into the others, so two gaps can otherwise land on the same guessed time (e.g.
    several generic "_default" categories all defaulting to a similar time of day). A draft
    that no longer fits before midnight after nudging is dropped rather than kept invalid.
    """
    today = date.today()
    placed: List[Task] = [t for t in pet.tasks if t.due_date == today]
    result = []
    for draft in sorted(drafts, key=lambda d: d.task.start_time):
        task = draft.task
        while True:
            clash = next((t for t in placed if task.overlaps(t)), None)
            if clash is None:
                break
            try:
                task = replace(task, start_time=clash.end_time())
            except ValueError:
                task = None
                break
        if task is None:
            continue
        placed.append(task)
        draft.task = task
        result.append(draft)
    return result


def generate_suggestions(
    client: ClaudeClient,
    owner: Owner,
    pet: Pet,
    dismissed: Iterable[Tuple[str, str]] = frozenset(),
    pending: Iterable[SuggestionDraft] = (),
) -> List[SuggestionDraft]:
    """Return fresh suggestions for pet's current gaps, skipping any gap already dismissed or
    already represented in pending (so re-running this doesn't redraft and discard a suggestion
    the user hasn't acted on yet)."""
    dismissed_set = set(dismissed)
    pending_keys = {(d.pet_name, d.category_key) for d in pending if d.pet_name == pet.name}
    gaps = [
        category
        for category in detect_gaps(pet)
        if (pet.name, category.key) not in dismissed_set
        and (pet.name, category.key) not in pending_keys
    ]
    drafts = [draft_suggestion(client, pet, owner, category) for category in gaps]
    return _deconflict_drafts([d for d in drafts if d is not None], pet)
