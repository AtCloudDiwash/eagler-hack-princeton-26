# Sponsor Strategy

Focus on the following sponsors/prizes:

- **CoStar Group (Commercial Real Estate Data)**
  - *Fit:* We directly use CoStar data and related property analytics (Matterport and Vexcel).
  - *Action:* Lead the demo with the real Vexcel data: live aerial and angled imagery, the AI building footprint, rooftop HVAC unit counts and roof condition feeding the checks and the cost estimate.
  - *Built (real):* `vexcel_provider` calls the Vexcel API with the sponsor key (ortho, oblique-north, `/property/extract`), caches imagery server-side, and turns AI facts into evidence: rooftop units → prorated HVAC share ("verify with landlord"), roof condition → `roof_condition` criterion and roof repair cost, footprint → overlay box, paved area → parking estimate. Verified end to end on 5 Houston buildings (the key is geofenced to Los Angeles + Houston).
  - *Built (ready for data):* `costar_provider` (tolerant `map_costar_listing`; sample listings at real Houston buildings until access arrives, labelled "Sample listing") and `matterport_provider` (floor plan + 3D tour iframe; no tour links yet). Report overlays and evidence chips show which source produced each finding (see [INTEGRATIONS.md](INTEGRATIONS.md), [VISION_OVERLAYS.md](VISION_OVERLAYS.md)).
  - *Prize:* Emphasize solving CoStar’s challenge by combining multi-source property data. Mention CoStar integration in marketing blurb.
  - *Tech:* Swap the Houston sample listings for real CoStar listings (with sponsor permission) as soon as access is available; the Vexcel side already uses real data.

- **Peri (Forward Deployed Challenges)**
  - *Fit:* Show we talked to a real small business owner (restaurant or clinic) and included their feedback.
  - *Action:* Include a comment or slide in pitch: “We validated with [Name, Role] from [Business] who said *‘The worst surprise was that …’* and coded for that exact problem.”
  - *Prize:* Document the interview notes in our design (maybe as an appendix or comment).

- **Amazon (AWS, AI services)**
  - *Fit:* AWS for hosting or AI.
  - *Action:* If time allows, deploy the backend on AWS (Elastic Beanstalk or EC2) or use AWS Lambda for microservices.
  - *Optional:* Use AWS Textract or Rekognition for any image analysis (though not needed for MVP).
  - *Status:* Not deployed; runs locally. The backend is a single uvicorn process with SQLite, so it is easy to containerize.
  - *Prize:* Mention AWS credits for hosting and using AWS for reliability.

- **Scale AI, LangChain, Agent Platforms**
  - *Fit:* Potential use of LLM orchestration or datasets.
  - *Built:* A local LLM (qwen3:8b on Ollama, `LLM_PROVIDER=ollama`) parses the free-text requirements (regex fallback) and writes a grounded plain-English summary of the finished ranking (rejected if it cites a number not in the results). Claude is a config switch (`LLM_PROVIDER=anthropic`). Costs, scores, statuses and ranks stay deterministic. The agent pipeline is plain Python functions; LangChain was not needed.
  - *Note:* Keep it simple; do not overshoot scope.

- **Photon, arlq, ChatOverflow, Projects Board, Justin Bojarski**
  - *Fit:* These sponsors are more community/prizes. Not specific tech requirements.
  - *Action:* In Devpost or pitch, acknowledge Princeton CS and general idea value.
  
**Key Point:** Emphasize *unique multi-layer analysis using sponsor data.* In demo and presentation, cite that we are solving a "CoStar challenge" by combining listing data, real Vexcel aerial intelligence, 3D-tour data, and Houston's actual parking and deed-restriction rules into one agent.
