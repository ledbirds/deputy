---
company: "[redacted, a public fintech]"
role: "AI Solutions Engineer"
source: greenhouse
discovered: 2026-07-28
posted: 2026-07-01
comp: "[redacted]"
location: Remote
score: 87
scores: {seam: 26, coverage: 20, seniority: 12, domain: 15, trajectory: 9, practical: 5}
unmet_must_haves: ["CI/CD pipelines and containerization, no demonstrable production experience"]
tier: 3
state: pending-approval
routing_note: "Scored into the auto-apply band but blocked by the unmet-must-have override. Requires APPROVE."
---

> **Sanitised.** Real output from the discovery agent. The company, the URL,
> compensation, my name, and my employers are redacted. The scores, the
> reasoning and the structure are exactly as the agent wrote them.
>
> This is the file that made me trust the rubric, and it is also the file that
> shows why a score alone is not enough. It scored 87, which is inside the
> auto-apply band, and it was not auto-applied. Two mandatory overrides exist
> for exactly this, and one of them fired.

## Why it scored 87

The highest-scoring role in the first sweep, and it earns it on seam fit. The
team is an embedded product-engineering group that owns data, AI, and
infrastructure for an internal function: pipelines, dashboards, AI tooling, and
production apps. The posting's fifth must-have is the ability to work across the
technical and business boundary and translate constraints in both directions.
That sentence describes the whole career arc: support, to analytics, to product
launch, to bank data engineering is a decade-long practice at exactly that
translation.

Domain scored maximum on two independent grounds. The company is in lending,
which is where the regulated-banking background plus a large-scale
fair-lending analysis is uncommon depth. And the data stack named in the posting
is the same one currently run day to day.

The fourth must-have, "demonstrated builder disposition, has created something
from nothing", is where the personal system stops being a curiosity and becomes
the strongest evidence on the page. A deployed edge worker, ten-plus autonomous
routines, and an orchestrator that runs unattended is a direct answer to that
requirement, and almost no other candidate for this role will have one.

No stated years-of-experience floor. **That is the single biggest unlock in the
entire sweep**, five of the eight roles found demand 8-10+ years against 4.5.

## What is unmet

**CI/CD pipelines and containerization**, named in must-have #2. Version control
is genuine: the vault is git-synced with a custom merge driver, and the worker
deploys from source. CI/CD as a discipline, and containerization, are not
demonstrable. This is one unmet must-have rather than three, so it does not
trigger the score cap. **It does trigger the auto-apply override.**

Must-have #1, "software engineering foundation, has built, deployed, and
maintained production applications", is a judgment call and worth stating
plainly rather than burying. That has been done, but outside employment. The
system is production in every meaningful sense: it runs unattended, it has
uptime, it has failure modes that have been debugged. It is not a professional
engineering title.

**The application should claim the former and never imply the latter.**

## The angle

Lead with the builder evidence, not the resume chronology. The letter opens on
the system that was built and is operated, connects it to what the team does,
and only then reaches back for the enterprise credibility. Reversing that order
buries the strongest asset behind a career story that reads as a pivot.

Second beat is the translation layer: being the person between the business and
the data in a regulated environment is a harder version of the same job this
team does internally.

## The risk

The engineering-title gap is real and a technical screen will find it. If the
loop tests containerization or pipeline tooling directly, this does not convert,
and no amount of framing changes that. Worth applying anyway because the seam
requirement is unusually explicit and the years floor is absent, which together
make this the best-shaped role in the sweep.

---

## Why this file is in the repo

Three things it demonstrates that the code alone does not.

**The score is not the decision.** 87 is inside the auto-apply band. It was
routed to a human anyway, because a mandatory override caught a single unmet
must-have. That is the same asymmetry `deputy`'s policy engine encodes: a missed
opportunity costs a week, an overstatement costs a relationship.

**The agent argues against itself.** "What is unmet" and "The risk" are not
decoration. An agent that only produces reasons to proceed is a generator of
justifications, not a judgment, and its output cannot be trusted precisely when
it matters.

**It names the line it must not cross.** "Claim the former and never imply the
latter" is the agent writing down, in advance, the exact sentence that would
have been a lie. That is what the no-fabrication rule looks like when it is
actually operating rather than sitting in a constitution.
