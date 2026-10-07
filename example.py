from datetime import date, timedelta

from saclay_edt import CelcatClient

c = CelcatClient("sciences")  # prompts for login/password only if the saved session is missing/expired
c.ensure_authenticated()

groups = c.list_groups("L3 CHI")
print(f"{len(groups)} groups, e.g.:", [g.id for g in groups[:5]])

group = groups[0].id
today = date.today()
for e in c.get_timetable(group, today, today + timedelta(days=7)):
    print(e.start, e.end, e.category, e.modules, e.details[2:3])

print(c.get_courses(group, today, today + timedelta(days=120)))
