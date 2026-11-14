# Sponsor Strategy

Focus on the following sponsors/prizes:

- **CoStar Group (Commercial Real Estate Data)**
  - *Fit:* We directly use CoStar data and related property analytics (Matterport and Vexcel).
  - *Action:* Highlight the use of CoStar's market data (even if mocked) and analytics from Matterport/Vexcel.
  - *Built:* `costar_provider` (listings, tolerant `map_costar_listing`), `matterport_provider` (floor plan + 3D tour embed), `vexcel_provider` (aerial). Mock fixtures by default, live behind `USE_MOCK_DATA=false` + keys with fixture fallback. Report overlays show which source produced each finding (see [INTEGRATIONS.md](INTEGRATIONS.md), [VISION_OVERLAYS.md](VISION_OVERLAYS.md)).
  - *Prize:* Emphasize solving CoStar’s challenge by combining multi-source property data. Mention CoStar integration in marketing blurb.
  - *Tech:* If possible, use any CoStar-provided sample dataset or API (with sponsor permission) instead of generic data.

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
  - *Built:* Optional Claude requirements parser (`ANTHROPIC_API_KEY`, regex fallback). The five-step agent pipeline is plain Python functions; LangChain was not needed.
  - *Note:* Keep it simple; do not overshoot scope.

- **Photon, arlq, ChatOverflow, Projects Board, Justin Bojarski**
  - *Fit:* These sponsors are more community/prizes. Not specific tech requirements.
  - *Action:* In Devpost or pitch, acknowledge Princeton CS and general idea value.
  
**Key Point:** Emphasize *unique multi-layer analysis using sponsor data.* In demo and presentation, cite that we are solving a "CoStar challenge" by combining building data, 3D tours, and zoning rules into one agent.
