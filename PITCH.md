# Pitch Playbook: Turnkey Matchmaker (HackPrinceton Fall 2026)

You get 2 minutes live plus an optional 2-minute video. Every line below helps with one of the
four scores: **Creativity, Utility, Charity, Avidity**.

---

## 1. Decisions to make now

| Decision | Choice | Why |
|---|---|---|
| Main track | **Business and Enterprise** | A small-business tool built on commercial real-estate data. Other teams will push "social good" here; our Charity story makes us stand out. |
| Special tracks | CoStar, Peri, **LangChain** (see §10), plus any other LLM/agents track you qualify for | CoStar: Vexcel data, Matterport-ready. Peri: needs a real owner interview (see §6). LangChain: the whole agent layer is built on LangChain Deep Agents. |
| Which build to demo | **v2 (repo root)**: map, live Vexcel, agent log, dashboard | It looks the most impressive. Borrow v1's main point: the cheapest rent is not the cheapest space. |
| One-sentence pitch | *"Listings tell you the rent. We tell you what it will actually cost to open there, and whether you're even allowed to."* | Say it word for word, twice: at the start and at the end. |

---

## 2. The "ah-ha" moment (build the pitch around this)

> **The space with the lowest rent is often the most expensive one to open.**

A former restaurant already has a hood, a grease trap and gas. A cheaper shell doesn't. One
industry survey puts taking over a former restaurant at **about $73/sq ft, versus about $193/sq ft
for new construction**. On 2,000 sq ft that's a gap of about $240k, hidden behind a rent difference
of a few hundred dollars a month. A first-time owner learns this *after* signing the lease.

On screen, show **two buildings side by side**: the low-rent one loses, and the dashboard explains
why with evidence (no rooftop units seen from the air, a deed restriction, parking short of
Houston §26-492). That reversal is the ah-ha.

The second ah-ha, for technical judges: **"The AI is not allowed to make up numbers."** Agents
gather evidence and every claim cites `E#`. Python does the scoring, verified rules override agent
opinions, and "not detected" never blocks a space. Say it in one line, then move on.

---

## 3. The 2-minute live script (practice with a timer, 5+ times)

**Roles:** A speaks, B drives the laptop. B never talks while A talks.

| Time | Who | Say | On screen |
|---|---|---|---|
| 0:00-0:20 | A | "Meet Maria. She saved for ten years to open her first restaurant. She found a space for $2,800 a month and signed. Then the contractor told her it needs a $140,000 hood and grease trap, and the deed bans food service. She never opens. **Listings tell you the rent. Nobody tells you the cost to open.**" | Title slide or the home page, with the query already typed |
| 0:20-0:35 | A | "Turnkey Matchmaker: describe your business in plain English and pick a building on a live aerial map." | B presses enter: *"40-seat restaurant with a kitchen in Houston Heights"*. Candidates appear on the Vexcel map. |
| 0:35-1:05 | A | "Five AI agents now investigate this building for *your* business: one reads Vexcel's aerial AI data (roof condition, rooftop HVAC units), one checks the neighborhood and competition, one checks Houston's real parking code and deed restrictions, and a cost agent prices only what the evidence shows is needed." | B clicks a building, then Analyze. The live agent log scrolls. **After ~5 s, open the pre-run result** (don't wait live). |
| 1:05-1:35 | A | "Here's the verdict. This one's rent is $600 a month higher, but it's **$180k cheaper to open**, because it's a former restaurant. And this one is disqualified: a deed restriction bans food service. Every finding links to its evidence, and when we don't know something, we say *unknown* and tell you what to ask the landlord." | Compare view: the two buildings side by side. Point at the verdict, the cost range, one evidence chip, one "unknown" item. |
| 1:35-1:50 | A | "The AI never makes up a number: agents gather evidence, deterministic rules score it. And adding a new business type or rule is just a YAML edit; we support restaurants, dental clinics, gyms, retail and offices today." | Quickly show `business_types.yaml` or the business switcher (optional) |
| 1:50-2:00 | A+B | "We talked to [owner name] at [business], and they said: *'[quote]'*. That's who this is for. **Listings tell you the rent. We tell you the cost to open.**" | Back to the dashboard hero |

> Swap in the **real numbers from your pre-run analyses** before practicing. Never say a figure
> the screen doesn't show. Judges notice.

**Live-demo safety rules**
- **Pre-run 3 analyses** (the winner, the low-rent trap, the disqualified one) and keep each in its own tab. The multi-agent run goes through Codex/Claude CLIs and is slow. Start one live for drama, then switch tabs.
- Warm the Vexcel cache and the demo fixture beforehand. Have `/analysis/demo` as a fallback if the Wi-Fi dies.
- Before judging: browser zoom 125%, notifications off, dark mode, close every other tab, never show `.env`.
- Keep the video loaded on a phone as a last resort.

---

## 4. Scoring map: what to show for each criterion

| Criterion | What judges need to see | Our proof |
|---|---|---|
| **Creativity** | A problem they didn't know existed, plus a clever method | The "cheapest rent is the most expensive" reversal; reading HVAC and roof condition *from aerial imagery*; agents that run follow-ups only when the answer could change the verdict |
| **Utility** | It works, and has depth | A real end-to-end flow on live Vexcel data in Houston, real municipal code with citations, five business types, side-by-side comparison, landlord questions, an SQLite history, tests (`pytest`), Docker Compose |
| **Charity** | A specific need, and who it serves | First-time and immigrant owners without an architect or broker; it brings due diligence that costs thousands to people who can't pay for it; small businesses employ about half the US private workforce |
| **Avidity** | Passion and polish, future plans | The Maria story, a confident hand-off, the Devpost roadmap (§5), "we're going to pilot this with [a local SBDC / the owner we interviewed]" |

---

## 5. Devpost write-up (paste and edit)

**Tagline:** Listings show the rent. We show the real cost to open, and whether you're even allowed to.

**Inspiration**
Most small-business owners pick a space based on rent. The expensive surprises come later: a missing
hood and grease trap, a deed restriction against food service, a parking minimum you can't meet.
A second-generation restaurant space can cost a fraction of a shell to open, but no listing site
tells you which is which. Big chains have site-selection teams; a first-time owner has Google. We
wanted to give the corner bakery the site-selection analyst it can't afford.

**What it does**
Describe your business in plain English ("40-seat restaurant with a kitchen in Houston Heights").
Turnkey Matchmaker finds candidate buildings on a live Vexcel aerial map. For the one you choose,
a team of AI agents investigates whether it fits *your* business:
- **Vexcel agent**: roof condition, rooftop HVAC units, footprint and paving from aerial AI.
- **Neighborhood agent**: competition, demand and transit from OpenStreetMap and Census data.
- **Compliance agent**: permitted use, deed restrictions and Houston's §26-492 parking minimums, with citations.
- **Cost agent**: a deterministic, evidence-driven build-out cost range.

You get a verdict, a confidence score, evidence for every claim, an honest "unknown" where data runs
out, questions to ask the landlord, and a side-by-side comparison across buildings.

**How we built it**
Next.js + Tailwind front end; FastAPI + SQLite back end. Agents run on LangChain Deep Agents, using
an LLM fallback chain (Codex CLI → Claude Code CLI → local Ollama). Every tool result becomes an
evidence ID; citations to evidence that doesn't exist are removed; verified rules and the cost
engine override agent opinions; Python does all scoring. Metrics, business types, jurisdictions and
cost bands are all YAML, so adding a business type needs no code.

**Challenges**
- Vexcel has no listing search, so we built discovery from parcel extraction plus a deterministic pre-screen.
- Stopping LLMs from inventing numbers led to the evidence-ID system and "rules beat opinions".
- "0 AC units detected" doesn't mean "no HVAC". We taught agents the detection limits of each data source.

**Accomplishments**
A full end-to-end analysis on real aerial data; real municipal code with citations; an AI that says
"I don't know" instead of guessing.

**What we learned**
[Fill in: one technical lesson and one learned from the business-owner interview.]

**What's next**
CoStar listing and rent feeds; Matterport interior scans to check the kitchen and restrooms; more
cities' codes; a "send to landlord" negotiation letter; a pilot with [local SBDC / owner].

**Built with:** nextjs, react, typescript, tailwind, python, fastapi, sqlite, langchain, vexcel, openstreetmap, census-api, docker

---

## 6. Peri prize: do this today (30 minutes)

Walk to a restaurant, café or salon near campus. Ask:
1. "How did you pick this space?"
2. "What did opening cost that you didn't expect?"
3. "Would a report like this (show the phone) have changed your decision?"

Get a name and permission, one quote, and a photo if they agree. Put the quote on the last slide, in
the Devpost and in the video. A real person's voice is the strongest Charity *and* Avidity evidence
you can have. Don't make one up; if nobody agrees, say "we spoke with owners who told us…" and
describe it honestly.

---

## 7. Video (≤ 2:00): shot list

1. **0:00-0:12** Black screen, white text: *"Taking over a former restaurant: ~$73/sq ft. Building from a shell: ~$193/sq ft. The listing shows neither."* (Only put a stat on screen if you can source it.)
2. **0:12-0:25** The owner interview clip (phone video is fine), or the Maria narration over B-roll of empty storefronts.
3. **0:25-1:30** Screen recording of the §3 flow with voice-over. Cut out the waiting with a jump cut over the agent log ("five agents, about a minute").
4. **1:30-1:50** A quick architecture card: Vexcel + OSM + Census → 5 agents → evidence → Python scoring → verdict.
5. **1:50-2:00** The one-sentence pitch + team names + GitHub URL.

Record at 1080p, use background music at low volume, and add captions (judges often watch muted).

---

## 8. Judge Q&A: have these answers ready (≤ 15 s each)

- **"Is the data real?"** Vexcel aerial and property AI data are live (key geofenced to Houston/LA). Houston's rules are researched with citations. CoStar listings and Matterport aren't connected, and the UI labels that clearly.
- **"What if the AI hallucinates?"** It can't change scores. Every claim needs an evidence ID, unsupported blockers are downgraded, and Python plus verified rules decide.
- **"How accurate are the costs?"** They're ranges from documented cost bands, not quotes. The point is to rank spaces correctly and flag the big-ticket items before you sign.
- **"Business model?"** Freemium for owners; paid for brokers, SBDCs and lenders (SBA lenders want this due diligence); a data partnership with CoStar.
- **"Why not just hire a broker?"** Tenant brokers mostly look at rent and terms; architects charge before you've chosen a site. This is the step before both, and it costs nothing.
- **"How does it scale to new cities and businesses?"** YAML: add a jurisdiction's rules or a business type's metrics. No code changes.

---

## 9. Final checklist (before 8 AM Sunday)

- [ ] Public GitHub repo; README top section = one-sentence pitch + screenshot/GIF + run command
- [ ] Devpost: track = Business and Enterprise; special tracks chosen; Discord usernames added
- [ ] Video uploaded (unlisted YouTube is fine), link on Devpost
- [ ] 3 pre-run analyses saved; demo fixture recorded; cache warm
- [ ] Owner quote collected and dropped into the script, slide, Devpost and video
- [ ] Script practiced 5+ times at **≤ 1:55**
- [ ] Laptop charged, charger packed, phone hotspot ready

---

## 10. LangChain special track

Before submitting, check that the Devpost lists a LangChain prize, and read its exact criteria.

**What's already built on LangChain** (point judges to these files):

| What | Where | What to say about it |
|---|---|---|
| 5 domain agents built with `create_deep_agent` (Deep Agents on LangGraph) | `backend/agents/base.py:243`, `agents/*_agent.py` | "Each agent is a Deep Agent with only its own domain tools. We removed the default file, shell and sub-agent tools." |
| A custom `BaseChatModel` that wraps local CLIs (Codex, Claude Code) | `services/cli_chat.py`, `codex_chat.py`, `claude_chat.py` | "We wrote our own LangChain chat models that turn a local coding CLI into a tool-calling, structured-output model, so LangGraph runs tools the same way it would with any provider." |
| A fallback chat model: Codex → Claude Code → Ollama, with usage-limit cooldowns | `services/llm.py` (`FallbackChat`) | "If one provider hits its usage limit, the analysis switches to the next one mid-run and keeps going. The live log shows the switch." |
| `ModelCallLimitMiddleware` + per-agent tool budgets + `ToolStrategy` structured output | `agents/base.py` | "Bounded agents: there's a cap on model calls and tool uses, and no repeated tool calls." |
| Every tool result becomes an evidence ID (`E#`); unsupported citations are removed | `agents/base.py` (tool decorator), `multi_agent_engine.py` | "LangChain tools that create their own audit trail." |
| Orchestration in two phases + targeted follow-ups only when they could change the verdict | `multi_agent_engine.py` | "Phase 2's cost agent uses phase 1's findings. Follow-ups run only if resolving an unknown could change the verdict." |

**Line for the live pitch** (replaces the 1:35-1:50 block when a LangChain judge is at the table):
> "Under the hood, five LangChain Deep Agents run on a fallback chain we wrote ourselves. Codex CLI,
> Claude Code and local Ollama are each wrapped as a LangChain chat model. Agents gather evidence;
> they never set the score."

**Quick win (~15 min): LangSmith tracing.** LangChain/LangGraph send traces with no code changes once
these are set in `backend/.env`:
```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<your key>
LANGSMITH_PROJECT=turnkey-matchmaker
```
Open one analysis's trace during judging to show five agents running in parallel, each tool call,
and the provider switch. LangChain judges respond well to seeing that. Take a screenshot for
Devpost too. (First run one analysis and check that traces show up through the custom CLI models.)

**Devpost "Built with":** add `langchain`, `langgraph`, `deepagents`, and `langsmith` if you enable it.
