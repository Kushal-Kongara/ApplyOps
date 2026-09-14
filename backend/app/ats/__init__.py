"""ATS form-filling MVP: opens a real application page in a visible
browser and fills what it can confidently recognize -- name, contact,
links, work authorization/sponsorship/relocation from `applicant_profile.json`,
prepared answers from an application preparation, and the approved
resume PDF. Never submits. Only Lever is implemented this phase; Ashby
and Greenhouse are detected but not yet filled (see `app/ats/detect.py`).
"""
