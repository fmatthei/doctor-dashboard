# Doctor Dashboard — how to update

**`state.json` in this repo is the live data (source of truth).** The old Gist
(`e456b8a03df2c92ddec907ea977466bc`) is retired and out of date: never read from it,
write to it, or "refresh" `state.json` from it. No GitHub token is needed.

## To record a change (visit, booking, cadence, action)
1. Edit `state.json` here. Set `updatedAt` to now (UTC ISO). Never hardcode dates;
   use `datetime.date.today()` (America/Santiago) for anything date-relative.
2. Commit and push to `main`. That's all.

A GitHub Action (`.github/workflows/recompute.yml`) then runs automatically on every
`state.json` change (and twice a day) and commits `alerts/YYYY-MM-DD.txt` (14 days ahead),
`digest/YYYY-MM-DD.txt` (upcoming Mondays), `status.txt`, `today.txt` and `monday.txt`.
Never write those files by hand.

## How the pieces fit
- Dashboard (`index.html`) reads `state.json` from this repo via the GitHub API, with the
  Pages copy as fallback.
- Scheduled tasks: "Daily Alert" fetches `alerts/<today>.txt`; "Monday Digest" fetches
  `digest/<today>.txt`. Both files start with `COUNT|n`. Both emails end with a SYSTEM
  STATUS block built from `status.txt`.
- `scripts/recompute.py` ports the dashboard's status logic; a logic fix in one must be
  mirrored in the other.

## Data conventions
- A procedure or control (e.g. mole removal) is logged as a visit but does NOT change the
  item's `lastVisit` / cadence. Only regular check-ups reset the cadence.
- Booked actions (e.g. orzuelo surgeon) use `booked`, `bookedTime`, `doctor`, `clinic`
  on the action.
- Calendar: appointments that need commuting use banana color (colorId "5") plus a
  "Salir a [clinic]" event 30 minutes before.
