#!/usr/bin/env python3
"""Recompute today.txt and monday.txt from state.json using the real current date.

Port of the status engine in index.html (computeStatus). Runs daily in GitHub Actions
so the scheduled Claude tasks always read fresh files.

Usage: recompute.py STATE_JSON OUT_DIR [--schema]
"""
import calendar
import datetime as dt
import json
import os
import sys

REMINDER_WEEKDAY = 3  # Thursday: weekly "still not booked" reminder (Monday digest covers Mondays)


def today():
    # Workflow sets TZ=America/Santiago, so this is the real local date.
    return dt.date.today()


def d(s):
    return dt.date.fromisoformat(s[:10]) if s else None


def add_months(date, months):
    # Mirrors JS setMonth: overflowing days roll into the next month.
    m = date.month - 1 + months
    y, m = date.year + m // 12, m % 12 + 1
    last = calendar.monthrange(y, m)[1]
    if date.day <= last:
        return dt.date(y, m, date.day)
    return dt.date(y, m, last) + dt.timedelta(days=date.day - last)


def fmt_short(date):
    return date.strftime("%b %d")


def who(item):
    return ", ".join(x for x in (item.get("doctor"), item.get("clinic")) if x) or "-"


def compute_status(item, t):
    last = d(item.get("lastVisit"))
    snooze = d(item.get("snoozeUntil"))
    snoozed = bool(snooze and snooze > t)
    follow = item.get("followUp") or {}
    cadence = item.get("cadenceMonths")

    if cadence is None and not item.get("followUp"):
        return {"state": "asneeded", "snoozed": snoozed, "due": None, "lead": None}

    if follow.get("date"):
        due = d(follow["date"])
    else:
        due = add_months(last, cadence)

    if item.get("leadDaysOverride") is not None:
        lead = item["leadDaysOverride"]
    elif cadence:
        lead = min(round(cadence * 30.44 * 0.25), 90)
    else:
        lead = 30

    booked = d(item.get("booked"))
    if booked:
        if booked < t:
            state = "didyougo"
        elif booked <= due:
            state = "booked"
        else:
            state = "bookedlate"
    elif t > due:
        state = "overdue"
    elif (due - t).days <= lead:
        state = "booknow"
    else:
        state = "ontrack"
    return {"state": state, "snoozed": snoozed, "due": due, "lead": lead}


def human_span(days):
    if days >= 365:
        return f"{days / 365.25:.1f} years"
    if days >= 60:
        return f"{round(days / 30.44)} months"
    return f"{days} days"


def booked_time(item):
    for k in ("bookedTime", "time", "bookedAt"):
        v = item.get(k)
        if v:
            return str(v)
    return None


def booked_note(item):
    for k in ("bookedNote", "bookedReason", "bookedPurpose", "note"):
        v = item.get(k)
        if v:
            return str(v)
    return None


def build(state, t):
    items = state.get("items", [])
    actions = state.get("actions", [])
    by_id = {i.get("id"): i for i in items}
    rows = [(i, compute_status(i, t)) for i in items]

    # ---------- monday.txt ----------
    overdue, didyougo, tobook, upcoming, windows = [], [], [], [], []
    for item, st in rows:
        s = st["state"]
        if st["snoozed"]:
            continue
        if s == "overdue":
            days = (t - st["due"]).days
            overdue.append((days, f"OVERDUE|{item['name']}|{who(item)}|Due {st['due']} — {days} days past due ({human_span(days)})"))
        elif s == "didyougo":
            didyougo.append(f"DIDYOUGO|{item['name']}|{who(item)}|Booked {item['booked'][:10]} — did the visit happen?")
        elif s == "booknow":
            left = (st["due"] - t).days
            tobook.append((left, f"TIMETOBOOK|{item['name']}|{who(item)}|Due {st['due']} — {left} days left"))
        elif s in ("booked", "bookedlate"):
            b = d(item["booked"])
            extra = ", ".join(x for x in (booked_time(item), booked_note(item)) if x)
            info = f"{b}{', ' + extra if extra else ''} (in {(b - t).days} days)" if b > t else f"{b}{', ' + extra if extra else ''} (today)"
            upcoming.append(((b - t).days, f"UPCOMING|{item['name']}|{who(item)}|{info}"))
        elif s == "ontrack":
            opens = st["due"] - dt.timedelta(days=st["lead"])
            windows.append((opens, item["name"]))

    needs = []
    for a in actions:
        if a.get("done"):
            continue
        parent = by_id.get(a.get("parentId"), {})
        due = d(a.get("due"))
        if due and due < t:
            # An open action with a past deadline counts as overdue (e.g. the orzuelo referral).
            days = (t - due).days
            doctor = a.get("doctor") or parent.get("doctor")
            detail = a.get("notes") or ", ".join(x for x in (doctor, parent.get("clinic")) if x) or "-"
            overdue.append((days, f"OVERDUE|{a.get('title')}|{detail}|Due {due} — {days} days past due ({human_span(days)})"))
        elif not due and a.get("dateMode") == "push":
            info = f"Open {(t - d(a['created'])).days} days" if a.get("created") else "Open"
            if parent.get("name"):
                info += f" ({parent['name']})"
            needs.append(f"NEEDSDATE|{a.get('title')}|{a.get('notes') or 'Date needed'}|{info}")

    overdue.sort(key=lambda x: -x[0])
    tobook.sort(key=lambda x: x[0])
    upcoming.sort(key=lambda x: x[0])
    windows.sort()

    parts = []
    if overdue:
        parts.append(f"{len(overdue)} overdue")
    if didyougo:
        parts.append(f"{len(didyougo)} to confirm")
    if tobook:
        parts.append(f"{len(tobook)} to book")
    if needs:
        parts.append(f"{len(needs)} need a date")
    if upcoming:
        parts.append(f"{len(upcoming)} upcoming")
    title = " · ".join(parts) or "All clear"

    monday = [f"TITLE|{title}"]
    monday += [x[1] for x in overdue] + didyougo + [x[1] for x in tobook] + needs + [x[1] for x in upcoming]
    if windows:
        opens, name = windows[0]
        monday.append(f"NEXTWINDOW|{name}|{opens}|in {(opens - t).days} days")

    # ---------- today.txt (next 7 days) ----------
    alerts = []
    for off in range(7):
        day = t + dt.timedelta(days=off)
        for item, st in rows:
            if st["snoozed"]:
                continue
            b = d(item.get("booked"))
            if b and b == day + dt.timedelta(days=1):
                tm = booked_time(item)
                where = item.get("clinic") or ""
                msg = f"Tomorrow: {item['name']}{' ' + tm if tm else ''}{', ' + where if where else ''}"
                alerts.append(f"{day}|previsit|{msg}|{item.get('doctor') or '-'}")
            if b and b == day:
                note = booked_note(item)
                where = item.get("clinic") or ""
                msg = f"Today: {item['name']}{' — ' + note if note else ''}{', ' + where if where else ''}"
                alerts.append(f"{day}|dayof|{msg}|{item.get('doctor') or '-'}")
            if st["state"] == "booknow" and not b and day.weekday() == REMINDER_WEEKDAY:
                left = (st["due"] - day).days
                alerts.append(f"{day}|bookingReminder|Reminder: {item['name']} still not booked, due {fmt_short(st['due'])} ({left}d left)|{who(item)}")
    today_txt = alerts or ["NO_ALERTS"]
    return "\n".join(today_txt) + "\n", "\n".join(monday) + "\n"


def schema(state):
    out = {"topKeys": list(state.keys())}
    for k in ("items", "actions", "visits"):
        keys = set()
        for x in state.get(k, []):
            keys |= set(x.keys())
        out[k + "Keys"] = sorted(keys)
    out["settings"] = state.get("settings")
    out["actions"] = state.get("actions")
    out["itemsBooked"] = [
        {k: v for k, v in i.items() if k in ("name", "booked", "lastVisit", "cadenceMonths", "followUp", "leadDaysOverride")}
        | {k: v for k, v in i.items() if "book" in k.lower() or "time" in k.lower() or "note" in k.lower()}
        for i in state.get("items", [])
    ]
    return json.dumps(out, ensure_ascii=False, indent=1)


def main():
    state_path, out_dir = sys.argv[1], sys.argv[2]
    with open(state_path, encoding="utf-8") as f:
        state = json.load(f)
    if "--schema" in sys.argv:
        print(schema(state))
    t = today()
    today_txt, monday_txt = build(state, t)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "today.txt"), "w", encoding="utf-8") as f:
        f.write(today_txt)
    with open(os.path.join(out_dir, "monday.txt"), "w", encoding="utf-8") as f:
        f.write(monday_txt)
    print(f"--- computed for {t} ---")
    print("=== today.txt ===\n" + today_txt + "=== monday.txt ===\n" + monday_txt)


if __name__ == "__main__":
    main()
