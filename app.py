import logging
import os
from datetime import time
from typing import Optional

import streamlit as st

from care_ai import AnthropicClaudeClient, ClaudeClient, detect_gaps, generate_suggestions
from pawpal_system import Frequency, Owner, Pet, Priority, Scheduler, Task

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")


@st.cache_resource
def get_claude_client() -> Optional[ClaudeClient]:
    """Build the Claude client once per app process, or None if no API key is configured."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        return AnthropicClaudeClient()
    except Exception:
        logging.exception("Failed to initialize Anthropic client")
        return None


# Streamlit reruns this script on every interaction, so keep the Owner in session state.
if "owner" not in st.session_state:
    st.session_state.owner = Owner("Jordan", time(7, 0), time(20, 0))
owner = st.session_state.owner

# AI suggestion state: dismissed gaps are never re-suggested this session, and the pending
# suggestion list survives reruns so Approve/Reject buttons work after the page redraws.
st.session_state.setdefault("dismissed_gaps", set())
st.session_state.setdefault("ai_suggestions", [])
# The last generated plan is also kept in session state (not just read off a fresh Scheduler)
# so it keeps showing, alongside pending AI suggestions, across the reruns an Approve/Reject
# click triggers -- those reruns don't re-press "Generate schedule".
st.session_state.setdefault("plan_scheduled", [])
st.session_state.setdefault("plan_dropped", [])

st.title("🐾 PawPal+")

st.markdown(
    """
Welcome to the PawPal+ starter app.

This file is intentionally thin. It gives you a working Streamlit app so you can start quickly,
but **it does not implement the project logic**. Your job is to design the system and build it.

Use this app as your interactive demo once your backend classes/functions exist.
"""
)

with st.expander("Scenario", expanded=True):
    st.markdown(
        """
**PawPal+** is a pet care planning assistant. It helps a pet owner plan care tasks
for their pet(s) based on constraints like time, priority, and preferences.

You will design and implement the scheduling logic and connect it to this Streamlit UI.
"""
    )

with st.expander("What you need to build", expanded=True):
    st.markdown(
        """
At minimum, your system should:
- Represent pet care tasks (what needs to happen, how long it takes, priority)
- Represent the pet and the owner (basic info and preferences)
- Build a plan/schedule for a day that chooses and orders tasks based on constraints
- Explain the plan (why each task was chosen and when it happens)
"""
    )

st.divider()

st.subheader("Owner and Pets")
owner.name = st.text_input("Owner name", value=owner.name)

col_start, col_end = st.columns(2)
with col_start:
    window_start = st.time_input("Available from", value=owner.window_start, key="window_start")
with col_end:
    window_end = st.time_input("Available until", value=owner.window_end, key="window_end")
try:
    owner.set_window(window_start, window_end)
except ValueError:
    st.error("The available window must end after it starts. Keeping "
             f"{owner.window_start:%H:%M}-{owner.window_end:%H:%M}.")

with st.form("add_pet_form", clear_on_submit=True):
    pet_name = st.text_input("Pet name")
    species = st.selectbox("Species", ["dog", "cat", "other"])
    other_species = st.text_input("If other, what kind of pet?", placeholder="e.g. rabbit, parrot")
    if st.form_submit_button("Add pet"):
        try:
            if species == "other":
                if not other_species.strip():
                    raise ValueError("Please say what kind of pet it is.")
                species = other_species.strip().lower()
            owner.add_pet(Pet(pet_name.strip(), species))
        except ValueError as e:
            st.error(str(e))

if owner.pets:
    st.write("Pets: " + ", ".join(f"{p.name} ({p.species})" for p in owner.pets))
else:
    st.info("No pets yet. Add one above.")

st.markdown("### Tasks")

if owner.pets:
    with st.form("add_task_form"):
        # Select by name: Streamlit returns a copy of object options, so look up the real Pet.
        selected_pet = st.selectbox("Pet", [p.name for p in owner.pets])
        col1, col2 = st.columns(2)
        with col1:
            task_title = st.text_input("Task title", value="Morning walk")
            start = st.time_input("Start time", value=time(8, 0))
            frequency = st.selectbox(
                "Frequency", list(Frequency), format_func=lambda f: f.value
            )
        with col2:
            duration = st.number_input("Duration (minutes)", min_value=1, max_value=240, value=20)
            priority = st.selectbox(
                "Priority", list(Priority), index=1, format_func=lambda p: p.name
            )
        if st.form_submit_button("Add task"):
            try:
                pet = next(p for p in owner.pets if p.name == selected_pet)
                pet.add_task(
                    Task(task_title, start, int(duration), priority, frequency)
                )
            except ValueError as e:
                st.error(str(e))
else:
    st.info("Add a pet before adding tasks.")

scheduler = Scheduler(owner)
all_tasks = scheduler.sort_by_time(owner.get_all_tasks())
if all_tasks:
    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))
    st.write("Current tasks:")
    fcol1, fcol2 = st.columns(2)
    pet_choice = fcol1.selectbox("Filter by pet", ["All pets"] + [p.name for p in owner.pets])
    status_choice = fcol2.selectbox("Filter by status", ["All", "Pending", "Done"])
    shown = scheduler.sort_by_time(
        scheduler.filter_tasks(
            pet_name=None if pet_choice == "All pets" else pet_choice,
            completed={"All": None, "Pending": False, "Done": True}[status_choice],
        )
    )
    if not shown:
        st.info("No tasks match this filter.")
    st.table(
        [
            {
                "Time": f"{t.start_time:%H:%M}-{t.end_time():%H:%M}",
                "Pet Name": p.name,
                "Activity": t.name,
                "Priority": t.priority.name,
                "Frequency": t.frequency.value,
                "Status": "done" if t.completed else "pending",
            }
            for p, t in shown
        ]
    )

    st.markdown("### Edit or remove a task")
    labels = {
        t.id: f"{p.name}: {t.name} at {t.start_time:%H:%M}" + (" (done)" if t.completed else "")
        for p, t in all_tasks
    }
    task_id = st.selectbox("Task", list(labels), format_func=labels.get)
    pet, task = next((p, t) for p, t in all_tasks if t.id == task_id)
    with st.form("edit_task_form"):
        col1, col2 = st.columns(2)
        with col1:
            new_name = st.text_input("Task title", value=task.name, key=f"name_{task.id}")
            new_start = st.time_input("Start time", value=task.start_time, key=f"start_{task.id}")
            new_frequency = st.selectbox(
                "Frequency", list(Frequency), index=list(Frequency).index(task.frequency),
                format_func=lambda f: f.value, key=f"freq_{task.id}",
            )
        with col2:
            new_duration = st.number_input(
                "Duration (minutes)", min_value=1, max_value=240,
                value=task.duration_minutes, key=f"dur_{task.id}",
            )
            new_priority = st.selectbox(
                "Priority", list(Priority), index=list(Priority).index(task.priority),
                format_func=lambda p: p.name, key=f"prio_{task.id}",
            )
        save = st.form_submit_button("Save changes")
        complete = st.form_submit_button("Mark complete")
        remove = st.form_submit_button("Remove task")
        if save or complete or remove:
            try:
                if complete:
                    if task.completed:
                        raise ValueError(f"'{task.name}' is already complete")
                    next_task = scheduler.complete_task(pet, task)
                    st.session_state["flash"] = (
                        f"Completed '{task.name}'. Next {task.frequency.value} occurrence "
                        f"added, due {next_task.due_date}."
                        if next_task else f"Completed '{task.name}'."
                    )
                elif save:
                    pet.edit_task(task.id, {
                        "name": new_name, "start_time": new_start,
                        "duration_minutes": int(new_duration),
                        "priority": new_priority, "frequency": new_frequency,
                    })
                else:
                    pet.remove_task(task.id)
                st.rerun()  # redraw the task table with the change
            except ValueError as e:
                st.error(str(e))
elif owner.pets:
    st.info("No tasks yet. Add one above.")

st.divider()

st.subheader("Build Schedule")
st.caption("Places tasks by priority, moves or drops conflicts, and explains every decision.")

if st.button("Generate schedule"):
    scheduler.build_plan()
    conflicts = scheduler.find_conflicts()
    if conflicts:
        st.warning("Some tasks overlap (the plan below resolves them):\n\n" + "\n\n".join(conflicts))
    st.session_state["plan_scheduled"] = scheduler.scheduled
    st.session_state["plan_dropped"] = scheduler.dropped

    claude_client = get_claude_client()
    if claude_client is None:
        st.caption("AI suggestions unavailable: set the ANTHROPIC_API_KEY environment variable to enable them.")
    else:
        previous_suggestions = st.session_state["ai_suggestions"]
        new_suggestions = []
        for pet in owner.pets:
            new_suggestions += generate_suggestions(
                claude_client, owner, pet,
                dismissed=st.session_state["dismissed_gaps"],
                pending=previous_suggestions,
            )
        # Keep previous suggestions only if their gap is still open and still undismissed --
        # drops stale suggestions for a gap the user already covered by adding a task manually.
        open_gaps = {pet.name: {c.key for c in detect_gaps(pet)} for pet in owner.pets}
        kept_suggestions = [
            d for d in previous_suggestions
            if d.category_key in open_gaps.get(d.pet_name, set())
            and (d.pet_name, d.category_key) not in st.session_state["dismissed_gaps"]
        ]
        st.session_state["ai_suggestions"] = kept_suggestions + new_suggestions

# Today's plan: confirmed tasks (green, already validated by the scheduler) and pending AI
# suggestions (red, awaiting approval) rendered together as one chronological list, so a
# suggestion reads as a row in the schedule rather than a separate section. Read from session
# state (not straight off `scheduler`) so this keeps showing across the reruns an Approve/Reject
# click triggers -- those reruns don't re-press "Generate schedule".
plan_rows = [(e.final_start, "confirmed", e) for e in st.session_state["plan_scheduled"]]
plan_rows += [(d.task.start_time, "suggestion", d) for d in st.session_state["ai_suggestions"]]
plan_rows.sort(key=lambda row: row[0])

ROW_WIDTHS = (1.1, 1.1, 1.8, 0.9, 2.8, 1.3)

if not plan_rows:
    st.info('Nothing to schedule today yet. Add some tasks above, then click "Generate schedule."')
else:
    st.write(f"Today's plan for {owner.name}")
    header_cols = st.columns(ROW_WIDTHS)
    for col, label in zip(header_cols, ("Time", "Pet", "Activity", "Priority", "Status", "Action")):
        col.markdown(f"**{label}**")

    for _, kind, payload in plan_rows:
        row = st.columns(ROW_WIDTHS)
        if kind == "confirmed":
            entry = payload
            row[0].write(entry.time_range())
            row[1].write(entry.pet_name)
            row[2].write(entry.task.name)
            row[3].write(entry.task.priority.name)
            row[4].markdown(f":green[{entry.outcome.value}] — {entry.reason}")
            row[5].write("✅")
            continue

        draft = payload
        pet = next((p for p in owner.pets if p.name == draft.pet_name), None)
        if pet is None:
            st.session_state["ai_suggestions"].remove(draft)
            continue
        row_key = f"suggestion_{draft.pet_name}_{draft.category_key}"
        row[0].write(draft.task.start_time.strftime("%H:%M"))
        row[1].write(draft.pet_name)
        row[2].write(draft.task.name)
        row[3].write(draft.task.priority.name)
        row[4].markdown(f":red[Needs approval] — {draft.reason}")
        keep_col, reject_col = row[5].columns(2)
        if keep_col.button("Keep", key=f"{row_key}_keep"):
            try:
                pet.add_task(draft.task)  # already validated when it was drafted
            except ValueError as e:
                st.error(str(e))
            else:
                st.session_state["ai_suggestions"].remove(draft)
                # Rebuild the plan now instead of waiting for another "Generate schedule" click,
                # so the approved task shows up immediately as a confirmed row, while the rest
                # of the pending suggestions stay listed below for review.
                scheduler.build_plan()
                st.session_state["plan_scheduled"] = scheduler.scheduled
                st.session_state["plan_dropped"] = scheduler.dropped
                st.session_state["flash"] = f"Added '{draft.task.name}' for {pet.name}."
                st.rerun()
        if reject_col.button("✕", key=f"{row_key}_reject"):
            st.session_state["dismissed_gaps"].add((draft.pet_name, draft.category_key))
            st.session_state["ai_suggestions"].remove(draft)
            st.rerun()

if st.session_state["plan_dropped"]:
    st.write("Dropped tasks:")
    st.table(
        [
            {
                "Requested time": e.task.start_time.strftime("%H:%M"),
                "Pet Name": e.pet_name,
                "Activity": e.task.name,
                "Reason": e.reason,
            }
            for e in st.session_state["plan_dropped"]
        ]
    )
