# state-tenders

A family of the s1d-labs scrape pool: the tender portals of states that do not run GePNIC.

| Project | Portal | Stored |
|---|---|---|
| `state-tenders-bihar` | eproc2.bihar.gov.in | all past tenders since July 2020 (about 102,600): tender view, contract (firm, PAN, value), documents |
| `state-tenders-ap` | tender.apeprocurement.gov.in | every procurement id since May 2016 (about 852,000): notice page, documents page, documents; daily poll of current tenders |
| `state-tenders-ts` | tender.telangana.gov.in | the same, since September 2017 (about 682,000 ids) |
| `state-tenders-gujarat` | tender.nprocure.com | every tender id since 2023 (about 367,000): notice, bidders, AOC (final value, award date); documents of open tenders; awarded lists of 41 clients |
| `state-tenders-cg` | eproc.cgstate.gov.in | open tenders of all departments: tender view and documents, kept by a daily poll |

- The portals answer only from India, so the projects use `geo="IN"`: India pool servers only.
- Chhattisgarh refuses the Mumbai proxies. Its project is not in the pool; workers on dev-vps-3 (OVH Mumbai) run it.
- Public data only. No login, captcha or OTP is passed. Award data that sits behind a captcha is not collected.
- Pace: 4 or 5 workers per portal, at most one request per 1.5 seconds per worker.
- Documents: env `DOCS` per project (`all`, `works`, `road`, `none`; see `portal.want_docs`). AP, TS and Bihar use `road` because of
  bucket room; every record lists all its documents, so the rest can be fetched later.
- Full histories: `python seed_history.py [--skip FILE]` queues the id ranges and list pages of `family.HISTORY` once.

Setup: change `family.py`, then Actions -> setup. Local tests (from an Indian IP): `python bihar.py --local 945 300`, `python aptms.py --local tender.telangana.gov.in 1260`, `python cg.py --local`.
