from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from enum import Enum
from itertools import count
from typing import List, Optional, Tuple

_task_ids = count(1)


class Priority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class Frequency(Enum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"


class Outcome(Enum):
    KEPT = "kept"
    MOVED = "moved"
    DROPPED = "dropped"


def _minutes(t: time) -> int:
    """Return minutes since midnight for a time."""
    return t.hour * 60 + t.minute


def _to_time(minutes: int) -> time:
    """Return the time of day for a number of minutes since midnight."""
    return time(minutes // 60, minutes % 60)


@dataclass
class Task:
    name: str
    start_time: time
    duration_minutes: int
    priority: Priority = Priority.MEDIUM
    frequency: Frequency = Frequency.ONCE
    completed: bool = False
    id: int = field(default_factory=lambda: next(_task_ids))
    created_at: datetime = field(default_factory=datetime.now)  # display only; ties use id
    due_date: date = field(default_factory=date.today)

    def __post_init__(self):
        """Validate priority, duration and that the task ends before midnight."""
        if not isinstance(self.priority, Priority):
            raise ValueError("priority must be a Priority")
        if self.duration_minutes <= 0:
            raise ValueError("duration_minutes must be positive")
        # Keep the task inside one day so end_time() never wraps past midnight.
        if _minutes(self.start_time) + self.duration_minutes >= 24 * 60:
            raise ValueError("task must end before midnight")

    def mark_complete(self) -> None:
        """Mark this task as done; the scheduler skips completed tasks."""
        self.completed = True

    def next_occurrence(self) -> Optional["Task"]:
        """Build the next occurrence of a recurring task.

        A DAILY task comes back due 1 day after the later of today and its own due date, and a
        WEEKLY task 7 days after. For a task due today or earlier that is today + 1 day (or 7).
        For a copy due in the future that was finished early, it counts from that due date, so
        two copies never land on the same day. Date arithmetic uses timedelta, so month, year
        and leap-day rollover are handled.
        The copy keeps the name, time, duration, priority and frequency, but gets a new id,
        a new created_at and completed=False. A ONCE task returns None.
        """
        days = {Frequency.DAILY: 1, Frequency.WEEKLY: 7}.get(self.frequency)
        if days is None:
            return None
        return replace(
            self,
            completed=False,
            due_date=max(date.today(), self.due_date) + timedelta(days=days),
            id=next(_task_ids),
            created_at=datetime.now(),
        )

    def end_time(self) -> time:
        """Return start_time + duration_minutes."""
        end = _minutes(self.start_time) + self.duration_minutes
        return time(end // 60, end % 60)

    def overlaps(self, other: "Task") -> bool:
        """Return True if this task's time range overlaps other's."""
        # Back-to-back tasks (one ends exactly when the next starts) do not overlap.
        return (
            _minutes(self.start_time) < _minutes(other.end_time())
            and _minutes(other.start_time) < _minutes(self.end_time())
        )


@dataclass
class Pet:
    EDITABLE_FIELDS = ("name", "start_time", "duration_minutes", "priority", "frequency")

    name: str
    species: str
    tasks: List[Task] = field(default_factory=list)

    def add_task(self, task: Task) -> None:
        """Add a task to this pet, rejecting an exact duplicate.

        A duplicate is the same name (case-insensitive), start time and due date as a task
        this pet already has -- e.g. two "Morning walk"s both at 07:30 today. A second walk at
        a different time, or the same walk on a different day (such as a recurring task's next
        occurrence), is not a duplicate and is allowed.
        """
        duplicate = next(
            (
                t for t in self.tasks
                if t.due_date == task.due_date
                and t.start_time == task.start_time
                and t.name.strip().lower() == task.name.strip().lower()
            ),
            None,
        )
        if duplicate is not None:
            raise ValueError(
                f"{self.name} already has '{duplicate.name}' at {task.start_time:%H:%M} "
                f"on {task.due_date}"
            )
        self.tasks.append(task)

    def _find_task(self, task_id: int) -> Task:
        """Return this pet's task with the given id, or raise ValueError."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise ValueError(f"no task with id {task_id}")

    def edit_task(self, task_id: int, changes: dict) -> None:
        """Update the task with the given id using the given field changes.

        Only EDITABLE_FIELDS may change. The new values are validated first, so a bad
        edit raises ValueError and leaves the task exactly as it was.
        """
        task = self._find_task(task_id)
        bad = set(changes) - set(self.EDITABLE_FIELDS)
        if bad:
            raise ValueError(f"cannot edit: {', '.join(sorted(bad))}")
        updated = replace(task, **changes)  # runs the Task checks on the new values
        for name in changes:
            setattr(task, name, getattr(updated, name))

    def remove_task(self, task_id: int) -> None:
        """Remove the task with the given id, or raise ValueError if this pet has none."""
        self.tasks.remove(self._find_task(task_id))


@dataclass
class Owner:
    name: str
    window_start: time
    window_end: time
    pets: List[Pet] = field(default_factory=list)

    def __post_init__(self):
        """Validate the available window given at creation."""
        self.set_window(self.window_start, self.window_end)

    def set_window(self, start: time, end: time) -> None:
        """Set the daily available window, or raise ValueError (keeping the old one) if end is not after start."""
        if end <= start:
            raise ValueError("window_end must be after window_start")
        self.window_start, self.window_end = start, end

    def add_pet(self, pet: Pet) -> None:
        """Add a pet to this owner, rejecting duplicate pet names."""
        # Names must be unique because the plan identifies pets by name.
        if any(p.name == pet.name for p in self.pets):
            raise ValueError(f"a pet named {pet.name!r} already exists")
        self.pets.append(pet)

    def get_all_tasks(self) -> List[Tuple[Pet, Task]]:
        """Return every pet's tasks together as (pet, task) pairs."""
        return [(pet, task) for pet in self.pets for task in pet.tasks]


@dataclass
class PlanEntry:
    task: Task
    pet_name: str
    final_start: Optional[time]  # None when the task is dropped
    outcome: Outcome
    reason: str

    def time_range(self) -> str:
        """Return the final "HH:MM-HH:MM" time range, or an empty string if the task was dropped."""
        if self.final_start is None:
            return ""
        end = _to_time(_minutes(self.final_start) + self.task.duration_minutes)
        return f"{self.final_start:%H:%M}-{end:%H:%M}"


class Scheduler:
    def __init__(self, owner: Owner):
        """Create a scheduler for an owner with an empty plan."""
        self.owner = owner
        self.scheduled: List[PlanEntry] = []
        self.dropped: List[PlanEntry] = []

    def sort_by_time(self, pairs: List[Tuple[Pet, Task]]) -> List[Tuple[Pet, Task]]:
        """Sort (pet, task) pairs by task start time, earliest first.

        Equal start times are ordered by task id (creation order), so the result is always
        the same. Returns a new list; the input is not modified.
        """
        return sorted(pairs, key=lambda pt: (pt[1].start_time, pt[1].id))

    def filter_tasks(
        self, pet_name: Optional[str] = None, completed: Optional[bool] = None
    ) -> List[Tuple[Pet, Task]]:
        """Return the owner's (pet, task) pairs, optionally filtered.

        pet_name keeps only that pet's tasks, and completed=True or False keeps only done or
        pending tasks. A filter left as None is not applied, so both can be combined.
        Reads every pet's tasks through Owner.get_all_tasks().
        """
        return [
            (pet, task)
            for pet, task in self.owner.get_all_tasks()
            if (pet_name is None or pet.name == pet_name)
            and (completed is None or task.completed == completed)
        ]

    def find_conflicts(self) -> List[str]:
        """Return one warning message for each pair of overlapping pending tasks.

        Checks tasks across all pets, so it catches conflicts on the same pet or between
        pets. Completed tasks are ignored, and so are tasks due on different days. Tasks that
        only touch (one ends when the next starts) are not conflicts. The tasks are sorted by
        start time, so each task is compared only with the ones that start before it ends.
        Never raises: an empty list means no conflicts.
        """
        pairs = self.sort_by_time(self.filter_tasks(completed=False))
        warnings = []
        for i, (pet_a, a) in enumerate(pairs):
            for pet_b, b in pairs[i + 1:]:
                if b.start_time >= a.end_time():
                    break  # sorted by start time, so no later task can overlap a
                if a.due_date == b.due_date:  # b starts inside a, so they overlap
                    who = f"for {pet_a.name}" if pet_a is pet_b else f"for {pet_a.name} and {pet_b.name}"
                    warnings.append(
                        f"Warning: {a.name} ({a.start_time:%H:%M}-{a.end_time():%H:%M}) overlaps "
                        f"{b.name} ({b.start_time:%H:%M}-{b.end_time():%H:%M}) {who}"
                    )
        return warnings

    def complete_task(self, pet: Pet, task: Task) -> Optional[Task]:
        """Mark a task complete and automatically schedule its next occurrence.

        For a daily or weekly task, the next copy (from Task.next_occurrence) is added to the
        pet and returned. Returns None for a one-time task, or if the task was already
        completed, so completing twice never creates a duplicate.
        """
        if task.completed:
            return None
        task.mark_complete()
        next_task = task.next_occurrence()
        if next_task:
            pet.add_task(next_task)
        return next_task

    def build_plan(self, day: Optional[date] = None) -> None:
        """Build the plan for one day, with an outcome and a reason on every entry.

        Uses the pending tasks due on day (default today), read through the owner's pets.
        Tasks are placed in order of priority (high first), then earlier time, then id.
        A task outside the owner's window is dropped. A task that overlaps one already placed
        moves to the next free slot later in the day, or is dropped if none fits before the
        window closes. Task objects are never changed; a moved time lives in PlanEntry.final_start.
        scheduled is sorted by final start time, and dropped lists everything left out.
        """
        day = day or date.today()
        self.scheduled.clear()
        self.dropped.clear()

        todo = [(pet, task) for pet, task in self.filter_tasks(completed=False) if task.due_date == day]
        todo.sort(key=lambda pt: (-pt[1].priority.value, pt[1].start_time, pt[1].id))

        window_start, window_end = _minutes(self.owner.window_start), _minutes(self.owner.window_end)
        window = f"{self.owner.window_start:%H:%M}-{self.owner.window_end:%H:%M}"
        placed = []  # (start, end, task name) in minutes, for tasks already on the plan

        for pet, task in todo:
            start, length = _minutes(task.start_time), task.duration_minutes
            if start < window_start or start + length > window_end:
                self._drop(pet, task, f"outside available window ({window})")
                continue

            slot, blocker = start, None
            while True:  # jump past each overlapping task until the slot is free
                clash = next((p for p in placed if slot < p[1] and p[0] < slot + length), None)
                if clash is None:
                    break
                blocker = clash[2]  # the most recent clash is the one that set the final slot
                slot = clash[1]

            if slot + length > window_end:
                self._drop(pet, task, f"no free slot left in the day (overlapped {blocker})")
            elif slot == start:
                placed.append((slot, slot + length, task.name))
                self.scheduled.append(PlanEntry(
                    task, pet.name, task.start_time, Outcome.KEPT,
                    f"kept at requested time (priority {task.priority.name})"))
            else:
                placed.append((slot, slot + length, task.name))
                self.scheduled.append(PlanEntry(
                    task, pet.name, _to_time(slot), Outcome.MOVED,
                    f"moved from {task.start_time:%H:%M} to {_to_time(slot):%H:%M} "
                    f"because it overlapped {blocker}"))

        self.scheduled.sort(key=lambda e: (e.final_start, e.task.id))

    def _drop(self, pet: Pet, task: Task, reason: str) -> None:
        """Record a task as dropped from the plan, with the reason."""
        self.dropped.append(PlanEntry(task, pet.name, None, Outcome.DROPPED, reason))
