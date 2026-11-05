import logging
from datetime import time

from care_ai import detect_gaps
from logging_config import configure_logging
from pawpal_system import Frequency, Owner, Pet, Priority, Scheduler, Task

configure_logging()
logger = logging.getLogger(__name__)

ROW = "{:<11} | {:<8} | {:<14} | {:<8} | {}"


def print_table(title, pairs) -> None:
    """Print (pet, task) pairs as a labeled table under a title."""
    print(f"\n{title}")
    print(ROW.format("Time", "Pet Name", "Activity", "Priority", "Frequency"))
    print("-" * 60)
    if not pairs:
        print("(none)")
    for pet, task in pairs:
        print(ROW.format(
            f"{task.start_time:%H:%M}-{task.end_time():%H:%M}",
            pet.name,
            task.name,
            task.priority.name,
            task.frequency.value,
        ))


def print_plan(scheduler) -> None:
    """Print the generated plan: scheduled entries with outcome and reason, then dropped ones."""
    row = "{:<11} | {:<8} | {:<14} | {:<8} | {:<7} | {}"
    print("\nGenerated Plan")
    print(row.format("Time", "Pet Name", "Activity", "Priority", "Outcome", "Reason"))
    print("-" * 100)
    for e in scheduler.scheduled:
        print(row.format(e.time_range(), e.pet_name, e.task.name,
                         e.task.priority.name, e.outcome.value, e.reason))
    print("\nDropped")
    for e in scheduler.dropped:
        print(f"{e.task.start_time:%H:%M}  {e.pet_name:<5} {e.task.name:<14} {e.reason}")
    if not scheduler.dropped:
        print("(none)")


def print_care_gaps(owner: Owner) -> None:
    """Print deterministic care-gap categories per pet (no AI call: the CLI has no
    approve/reject flow, so drafting a suggestion nobody can act on would just burn an API call
    for discardable output). Run the Streamlit app to see and approve AI-drafted suggestions.
    """
    print("\nCare gaps (see the Streamlit app for AI-drafted suggestions)")
    for pet in owner.pets:
        gaps = detect_gaps(pet)
        if gaps:
            print(f"{pet.name}: missing {', '.join(g.key for g in gaps)}")
        else:
            print(f"{pet.name}: no gaps detected")


def main() -> None:
    logger.info("Starting PawPal+ CLI demo")
    owner = Owner("Jordan", window_start=time(7, 0), window_end=time(20, 0))

    rex = Pet("Rex", "dog")
    mia = Pet("Mia", "cat")
    owner.add_pet(rex)
    owner.add_pet(mia)

    # Added out of order on purpose, so sorting has something to do.
    rex.add_task(Task("Grooming", time(17, 0), 45, Priority.LOW, Frequency.WEEKLY))
    mia.add_task(Task("Play session", time(12, 30), 20))
    mia.add_task(Task("Breakfast", time(8, 0), 10, Priority.HIGH, Frequency.DAILY))
    rex.add_task(Task("Morning walk", time(7, 30), 30, Priority.HIGH, Frequency.DAILY))
    # Two tasks that collide with existing ones: one across pets, one on the same pet.
    rex.add_task(Task("Vet call", time(12, 30), 15, Priority.HIGH))
    rex.add_task(Task("Training", time(17, 15), 30))
    rex.add_task(Task("Early meds", time(6, 0), 10, Priority.HIGH))  # before the 7:00 window
    mia.tasks[1].mark_complete()  # Breakfast is already done

    scheduler = Scheduler(owner)
    print(f"Today's Schedule for {owner.name} "
          f"({owner.window_start:%H:%M}-{owner.window_end:%H:%M})")
    print_table("All tasks as added (unsorted)", owner.get_all_tasks())
    print_table("All tasks, sorted by time", scheduler.sort_by_time(owner.get_all_tasks()))
    print_table("Rex's tasks only", scheduler.sort_by_time(scheduler.filter_tasks(pet_name="Rex")))
    print_table("Pending tasks", scheduler.sort_by_time(scheduler.filter_tasks(completed=False)))
    print_table("Completed tasks", scheduler.sort_by_time(scheduler.filter_tasks(completed=True)))
    print_table("Mia's pending tasks",
                scheduler.sort_by_time(scheduler.filter_tasks(pet_name="Mia", completed=False)))

    print("\nConflict check")
    warnings = scheduler.find_conflicts()
    for warning in warnings:
        print(warning)
    if not warnings:
        print("No conflicts found.")

    scheduler.build_plan()
    logger.info(
        "Generated schedule: %d scheduled, %d dropped, %d conflict warning(s)",
        len(scheduler.scheduled), len(scheduler.dropped), len(warnings),
    )
    print_plan(scheduler)
    print_care_gaps(owner)

    # Recurring tasks: completing a daily or weekly task creates the next occurrence.
    print("\nCompleting recurring tasks")
    for pet, task in [(rex, rex.tasks[1]), (rex, rex.tasks[0]), (mia, mia.tasks[0])]:
        next_task = scheduler.complete_task(pet, task)
        if next_task:
            print(f"{pet.name}: {task.name} ({task.frequency.value}) done "
                  f"-> next due {next_task.due_date}")
        else:
            print(f"{pet.name}: {task.name} ({task.frequency.value}) done -> no next occurrence")


if __name__ == "__main__":
    main()
