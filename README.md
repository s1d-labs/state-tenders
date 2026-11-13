# state-tenders

A family of the s1d-labs scrape pool: the tender portals of states that do not run GePNIC.

| Project | Portal | Stored |
|---|---|---|
| `state-tenders-bihar` | eproc2.bihar.gov.in | past tenders of road and city departments: tender view, contract (firm, PAN, value), documents |
| `state-tenders-ap` | tender.apeprocurement.gov.in | current works tenders: notice page and documents, kept by a daily poll |
| `state-tenders-ts` | tender.telangana.gov.in | the same, for Telangana |
| `state-tenders-gujarat` | tender.nprocure.com | road works in progress and Roads and Buildings awards: notice, contract page, documents |
| `state-tenders-cg` | eproc.cgstate.gov.in | open tenders of all departments: tender view and documents, kept by a daily poll |

- The portals answer only from India, so the projects use `geo="IN"`: India pool servers only.
- Chhattisgarh refuses the Mumbai proxies. Its project is not in the pool; workers on dev-vps-3 (OVH Mumbai) run it.
- Public data only. No login, captcha or OTP is passed. Award data that sits behind a captcha is not collected.
- Pace: 2 workers per portal, at most one request per 2 seconds per worker.

Setup: change `family.py`, then Actions -> setup. Local tests (from an Indian IP): `python bihar.py --local 945 300`, `python aptms.py --local tender.telangana.gov.in 1260`, `python cg.py --local`.
