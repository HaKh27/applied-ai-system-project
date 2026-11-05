from datetime import time

from pawpal_system import Frequency, Owner, Pet, Priority, Task
from care_ai import CARE_GUIDELINES, detect_gaps, draft_suggestion, generate_suggestions, get_guidelines


class FakeClaudeClient:
    """Returns each string in `responses` in order, one per .generate() call. Records every
    prompt it was given in `.prompts` so tests can check what the model was grounded on."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return self.responses.pop(0)


def _owner_with(pet):
    owner = Owner("Jordan", time(7, 0), time(20, 0))
    owner.add_pet(pet)
    return owner


VALID_RESPONSE = (
    '{"name": "Morning walk", "start_time": "07:30", "duration_minutes": 25, '
    '"priority": "HIGH", "frequency": "daily", "reason": "Dogs need a daily walk."}'
)


def test_detect_gaps_flags_missing_categories_for_a_dog():
    pet = Pet("Rex", "dog")
    pet.add_task(Task("Grooming", time(17, 0), 45))

    keys = {c.key for c in detect_gaps(pet)}

    assert keys == {"walk", "feeding", "vet_checkup"}


def test_existing_task_covers_category_even_if_completed():
    pet = Pet("Rex", "dog")
    task = Task("Morning walk", time(7, 30), 30, frequency=Frequency.DAILY)
    pet.add_task(task)

    assert "walk" not in {c.key for c in detect_gaps(pet)}

    task.mark_complete()

    assert "walk" not in {c.key for c in detect_gaps(pet)}


def test_unknown_species_uses_default_guidelines():
    pet = Pet("Jack", "iguana")

    assert get_guidelines("iguana") is CARE_GUIDELINES["_default"]
    gap_keys = {c.key for c in detect_gaps(pet)}
    assert gap_keys == {c.key for c in CARE_GUIDELINES["_default"]}


def test_draft_suggestion_recovers_after_an_invalid_first_response():
    pet = Pet("Rex", "dog")
    owner = _owner_with(pet)
    category = get_guidelines("dog")[0]  # walk
    fake = FakeClaudeClient(["not json at all", VALID_RESPONSE])

    draft = draft_suggestion(fake, pet, owner, category)

    assert draft is not None
    assert draft.task.name == "Morning walk"
    assert draft.category_key == category.key
    assert len(fake.prompts) == 2
    assert "not valid JSON" in fake.prompts[1]


def test_draft_suggestion_gives_up_cleanly_after_max_attempts():
    pet = Pet("Rex", "dog")
    owner = _owner_with(pet)
    category = get_guidelines("dog")[0]
    fake = FakeClaudeClient(["nope", "still nope", "nope again"])

    draft = draft_suggestion(fake, pet, owner, category, max_attempts=3)

    assert draft is None
    assert len(fake.prompts) == 3


def test_every_surviving_suggestion_is_a_valid_task():
    for species in ("dog", "cat"):
        pet = Pet(f"Pet-{species}", species)
        owner = _owner_with(pet)
        for category in get_guidelines(species):
            response = (
                f'{{"name": "{category.key}", "start_time": "09:00", '
                f'"duration_minutes": {category.suggested_duration}, '
                f'"priority": "{category.suggested_priority.name}", '
                f'"frequency": "{category.suggested_frequency.value}", '
                f'"reason": "{category.guideline_text}"}}'
            )
            fake = FakeClaudeClient([response])

            draft = draft_suggestion(fake, pet, owner, category)

            assert draft is not None
            assert isinstance(draft.task, Task)


def test_prompt_is_grounded_in_the_real_guideline_text():
    pet = Pet("Rex", "dog")
    owner = _owner_with(pet)
    category = get_guidelines("dog")[0]
    fake = FakeClaudeClient([VALID_RESPONSE])

    draft_suggestion(fake, pet, owner, category)

    assert all(category.guideline_text in prompt for prompt in fake.prompts)


def test_generate_suggestions_spreads_out_colliding_draft_times():
    # Each category is drafted via an independent call with no visibility into the others, so
    # they can all land on the same guessed time -- simulate that here and confirm the
    # suggestions get spread apart instead of being shown stacked on the same slot.
    pet = Pet("Brownie", "dog")
    owner = _owner_with(pet)
    categories = get_guidelines("dog")
    responses = [
        f'{{"name": "{c.key}", "start_time": "10:00", "duration_minutes": 30, '
        f'"priority": "MEDIUM", "frequency": "once", "reason": "{c.guideline_text}"}}'
        for c in categories
    ]
    fake = FakeClaudeClient(responses)

    suggestions = generate_suggestions(fake, owner, pet)

    assert len(suggestions) == len(categories)
    starts = sorted(d.task.start_time for d in suggestions)
    assert starts == [time(10, 0), time(10, 30), time(11, 0), time(11, 30)]
