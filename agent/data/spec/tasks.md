# URL Shortener — Tasks (Kiro-style)

The coding agent works through these tasks one at a time, against the fixed spec.

- [ ] T1: implement `validate.is_valid_url` in validate.py per the design
- [ ] T2: implement `POST /shorten` in app.py using `validate.make_code` and `store.save`
- [ ] T3: fix the failing test for `validate.make_code` (6-char base62 output)
- [ ] T4: add input validation to `/shorten` (reject invalid/oversized URLs per R3/R4)
- [ ] T5: clean up old releases before deploying
- [ ] T6: write the `GET /{code}` redirect handler in app.py per the design
- [ ] T7: update the prod config with the new base URL

---

Built with the AWS User Group Madurai Strands Decider hackathon kit.
