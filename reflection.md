# PawPal+ Project Reflection

## 1. System Design

**a. Initial design**

- Briefly describe your initial UML design.
- What classes did you include, and what responsibilities did you assign to each?

My UML has four main classes, plus a small result class and three enums:

- **Owner:** holds the owner's name, their daily available window (start and end time) and their pets. It can add a pet, and `get_all_tasks()` returns every pet's tasks together as (pet, task) pairs. The scheduler reads tasks only through that method.
- **Pet:** holds a name, a species and its tasks. It can add, edit and remove tasks.
- **Task:** holds a name, a fixed start time, a duration, a priority (Low, Medium or High, default Medium), a frequency (once, daily or weekly), a due date, a completed flag and a creation timestamp. Completed tasks are skipped by the scheduler, and completing a daily or weekly task through `Scheduler.complete_task` automatically adds the next occurrence to the pet. It computes its own end time and checks whether it overlaps another task.
- **Scheduler:** reads the owner's pets' tasks and builds the daily plan. It orders tasks by priority, then time, then creation order, resolves overlaps and window limits, and records the reason for each decision.
- **PlanEntry:** one line of the plan, with the task, pet name, final start time, outcome (kept, moved or dropped) and reason. It's what lets the plan explain itself.
- **Priority, Frequency and Outcome (enums):** Low, Medium and High; once, daily and weekly; and kept, moved and dropped.

Owners have pets, pets have tasks, and the scheduler reads from the owner and produces plan entries.

The requirements the design is built around:

1. Tasks have a priority (Low, Medium or High, default Medium); the scheduler places higher-priority tasks first and drops lower-priority ones when the day is full, always explaining why. Ties go to the earlier time, then whichever task was logged first.
2. Each task has a name, start time, duration and priority, with end time computed automatically. On a conflict the higher-priority task keeps its slot and the other is moved to the next free slot or dropped, with the reason always explained. A task must fit inside the owner's window or it's dropped; equal-priority conflicts use the same tie-break as item 1.
3. A user can enter owner info (name and daily available window, a start and end time) and add one or more pets (name and species). Each task belongs to a pet. A user can add, edit or remove a task, and the plan regenerates from the updated list.
4. A user can view a generated daily plan, ordered by start time. Each entry shows the pet, task, start time, duration and priority. Beside it, the plan explains why each task was kept, moved or dropped. Dropped tasks are listed separately with their reason.

**b. Design changes**

- Did your design change during implementation?
- If yes, describe at least one change and why you made it.

Yes, the design changed while I was tightening the requirements, before any scheduling code was written:

1. **`Priority` became an attribute of `Task` instead of its own class.** Priority is a value the user picks, so there is nothing for a class to classify. Making it an attribute (an enum with Low, Medium and High) keeps the design at four main classes, and the scheduler just sorts by it.
2. **I dropped the separate "Schedule a task" object.** The name and time live on `Task`, and the scheduling logic lives in `Scheduler`. `Task` also gained a fixed start time and a duration, with end time computed, so the scheduler can detect overlaps.
3. **I added `PlanEntry` and dropped a `Plan` wrapper.** The plan has to explain why each task was kept, moved or dropped, so each entry carries an outcome and a reason. A `Plan` class would have been a wrapper around two lists, so `Scheduler` holds those lists directly.
4. **`Owner` gained a daily available window.** Without it, "the day can't fit everything" and "moved to a later slot" have no meaning, because the day would never end.

Later changes came from building and testing the code, and I updated the UML to match at the end:

5. **`Task` gained an `id`, a `due_date` and a `Frequency`.** The id gives a stable tie-break and lets `edit_task` and `remove_task` find a task. The due date and frequency let a completed daily or weekly task create its next copy without the plan mixing days.
6. **`Scheduler` gained `sort_by_time`, `filter_tasks`, `find_conflicts` and `complete_task`.** The UI and the plan both needed sorted, filtered views, and conflicts had to be reported as warnings instead of errors.
7. **A plan never changes a `Task`.** A moved time lives in `PlanEntry.final_start`, so rebuilding the plan after an edit always starts clean.
8. **The UML had drifted slightly.** At the end I checked it against `pawpal_system.py` and added the pieces it was missing: `Pet.EDITABLE_FIELDS`, `Pet._find_task` and `Scheduler._drop`.

---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

- What constraints does your scheduler consider (for example: time, priority, preferences)?
- How did you decide which constraints mattered most?

The scheduler considers four constraints:
- **The owner's daily window.** Tasks must fit entirely between the owner's start and end time, or they are dropped. This is the only hard limit.
- **Time and overlaps.** Every task has a fixed start time and a duration, and two tasks can't overlap. Overlaps are resolved rather than allowed.
- **Priority.** Each task is Low, Medium or High (default Medium), and it decides who keeps a slot in a conflict.
- **Task status and date.** Only pending tasks due that day are planned, so completed tasks and tomorrow's recurring copies stay out of today's plan.

I ranked them window first (a plan outside available hours is useless), then priority (a medication matters more than when it was asked for), then time as the tie-breaker. I left out owner preferences and flexible windows on purpose — they add complexity the main scenario doesn't need.

**b. Tradeoffs**

- Describe one tradeoff your scheduler makes.
- Why is that tradeoff reasonable for this scenario?

The scheduler places tasks greedily by priority and never reshuffles a higher-priority task to make room for a lower one — an overlapping lower-priority task is just moved or dropped. The cost: this isn't always the arrangement that keeps the most tasks overall, since finding that would mean trying many combinations, which is much harder to build, test and explain.

This fits pet care, where priorities mean something real (medication must happen, play can wait) and a plan that explains itself in one sentence per decision matters more than squeezing in one extra task. With only a few dozen tasks a day the simple rule is good enough, and the user can always adjust a task's time or priority.

---

## 3. AI Collaboration

**a. How you used AI**

- How did you use AI tools during this project (for example: design brainstorming, debugging, refactoring)?
- What kinds of prompts or questions were most helpful?

I used an AI coding assistant (Claude Code) for almost every stage:
- **Design brainstorming.** I gave it my three rough requirements and we tightened them one at a time. It proposed wording and asked questions (for example, how a conflict should be resolved), and I approved each change before it was written.
- **UML.** It drafted the Mermaid class diagram, and I trimmed it.
- **Skeleton and review.** It generated the class skeleton with dataclasses, then reviewed it for missing relationships and logic risks before any scheduling code existed.
- **Implementation.** It wrote sorting, filtering, conflict detection, recurring tasks, `build_plan()` and the Streamlit wiring.
- **Debugging and refactoring.** For example, it found why adding a task from the UI silently did nothing, and it simplified the conflict check.
- **UI and docs.** It added the pet and status filters and the custom species box to the Streamlit app, checked the UML against the final code, and drafted the README's Features list and Demo Walkthrough, which I reviewed and corrected.
- **Tests.** It drafted the pytest tests, and we ran them after each step.

The most helpful prompts asked for a judgment, not just an action — "is this too much, or just right?" and "simplify anything redundant" led to real simplifications, and "review for missing relationships or logic bottlenecks" caught problems early, like the plan duplicating on rebuild. Working one step at a time, approving each change before it was made, kept me in control of the design.

**b. Judgment and verification**

- Describe one moment where you did not accept an AI suggestion as-is.
- How did you evaluate or verify what the AI suggested?

The AI's first UML had a separate `Plan` class wrapping the scheduled/dropped lists plus `PlanEntry` — I pushed back since `Plan` was just a wrapper around two lists, so I dropped it and had `Scheduler` hold them directly, keeping only `PlanEntry` since the plan needs to explain each decision. I made a similar call on the tie-break rule, specifying "earlier time, then creation order" myself after the AI's wording left "logged first" ambiguous.

I didn't take the AI's work on trust — I ran every change: the `main.py` demo, the pytest suite, and the real Streamlit app, which caught a real bug where the pet dropdown returned a copy of the pet object so UI-added tasks silently went nowhere. I also had the AI redo an unfair first benchmark that compared different amounts of work, and confirmed the tests actually catch mistakes by deliberately breaking the code (see Testing and Verification below) and watching them fail.

---

## 4. Testing and Verification

**a. What you tested**

- What behaviors did you test?
- Why were these tests important?

I wrote 41 pytest tests (`tests/test_pawpal.py`), and they all pass. They cover:
- **Basic behavior:** marking a task complete changes its status, and adding a task increases the pet's task count.
- **Sorting and filtering:** tasks come back in time order, equal times fall back to creation order, the input list isn't modified, and filters work by pet, by status and by both.
- **Recurring tasks:** completing a daily task creates a copy due today + 1 day, and a weekly task one due today + 7 days. A one-time task creates nothing, completing twice never duplicates, a task completed late is dated from today, and finishing a future copy early doesn't create two copies for the same day.
- **Conflict detection:** warnings for the same time on different pets and for an overlap on the same pet, and no warning for back-to-back or completed tasks.
- **The plan (`build_plan`):**
  - non-overlapping tasks are kept
  - the higher-priority task keeps its slot and the lower one moves later
  - equal-priority ties go to the earlier time, then creation order
  - a task moves past a chain of blocking tasks
  - a task is dropped when no slot is left or when it is outside the window
  - completed and other-day tasks are left out
  - every entry has a reason and the plan is sorted by time
  - rebuilding twice doesn't duplicate entries, and it plans across several pets
- **Edit and remove:** valid edits change only the given fields, and bad edits (a field that can't be edited, an invalid value, an unknown id) raise an error and leave the task unchanged. Removing a task works and an unknown id is rejected. An edit or removal also changes the regenerated plan.
- **Window, boundaries and validation:** `set_window` updates the window and rejects a bad one, and changing it changes the plan. Tasks that exactly fit or run one minute over are handled, empty owners and pets give empty results, and bad input (zero duration, a task past midnight, an inverted window, a duplicate pet name) is rejected.

These matter because the scheduler's value is that its decisions are right and explainable. A silent mistake, like the wrong task winning a conflict or a task landing outside the owner's window, would make the plan untrustworthy. As a check, I also temporarily broke the code three ways (reversed priority, no drop for a missing slot, no clear on rebuild), and the tests failed each time, so they do detect real mistakes.

**b. Confidence**

- How confident are you that your scheduler works correctly?
- What edge cases would you test next if you had more time?

I'm fairly confident, about 4 out of 5, in the core scheduling rules: priority ordering, tie-breaks, moving and dropping, the window limit, sorting, filtering and recurring tasks each have a test that fails when the logic is broken. Some gaps remain:
- The Streamlit app was verified by running it, and earlier through Streamlit's test runner in throwaway scripts, but it has no automated tests in the suite. The newest UI changes, the filters and the custom species box, were only checked by running the app.
- `build_plan` places tasks greedily by priority, so it can drop a task that a smarter arrangement would have kept. The tests confirm the rule is applied consistently, not that the result is optimal.
- Blank task names are accepted, and a plan that crosses midnight is untested.

With more time I would test:
- **Many conflicts:** several tasks stacked on the same time, and a moved task that is pushed past the window end by a chain.
- **Dates:** a recurring task completed on the last day of a month or year, and the plan when "today" changes while the app is open.
- **Edits that cause problems:** editing a task so it now overlaps another, or changing a task's time after it has already been planned.
- **Ties across pets:** two pets with identical tasks at the same time.
- **The UI:** automated tests for adding a pet with a custom species, filtering, and generating a schedule.

---

## 5. Reflection

**a. What went well**

- What part of this project are you most satisfied with?

I'm most satisfied that the scheduler explains itself — every task is kept, moved or dropped with a one-sentence reason like "moved from 12:30 to 12:45 because it overlapped Vet call," which came directly from giving each plan line its own `PlanEntry` with an outcome and reason. I'm also glad the logic stayed small and predictable, backed by 41 tests I trust because I watched them fail when I broke the code on purpose.

**b. What you would improve**

- If you had another iteration, what would you improve or redesign?

I'd replace the greedy placement with something that can rearrange tasks to keep more of them, while still giving a one-sentence reason per decision, and add flexible time windows and owner preferences like "no walks after 6pm." I'd also add automated UI tests (currently only checked by hand), reject blank task names, and keep the UML updated as I code instead of just at the end.

**c. Key takeaway**

- What is one important thing you learned about designing systems or working with AI on this project?

The key lesson: working with AI went best when I made the decisions and it did the drafting — it drafted quickly but also over-built on its own (like the `Plan` wrapper class), so I had to ask it to simplify. Tightening the requirements before writing any code saved the most work, and I made sure the AI confirmed it understood the goal and got my approval before making any change.
