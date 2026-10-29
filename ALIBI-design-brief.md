# ALIBI — Design Brief
**Copernicus Marine Service Hackathon 2026 · Enhancing Maritime Security and Resilience**

## What we are building

ALIBI is an anomaly-triage layer for maritime monitoring systems. It takes vessels or events already considered unusual by a monitoring system, enriches them with independent evidence, and helps reduce the list to the cases that still deserve human attention.

The method is explanation: test how much of an unusual movement can be accounted for by the surrounding sea, the vessel’s own history, its location, traffic patterns, data quality and other available signals. ALIBI does not decide whether a vessel is good, bad or hostile. It shows what is unusual, what evidence helps explain it, what remains unexplained, and how confident that assessment is.

The intended product is middleware, not another AIS map. It should be possible to ingest data through APIs and expose scored, evidence-backed results through an API for integration into existing AIS monitoring and maritime-domain-awareness tools. The hackathon interface is a deliberately distinct, game-like science instrument: a way to demonstrate the method without pretending to replace established maritime interfaces.

> **The sea is the alibi.** Most unusual behaviour may have an ordinary explanation. The useful question is what remains after we have tested the explanations.

## Why ALIBI exists

False positives undermine trust in monitoring systems. When dashboards repeatedly flag ordinary activity, people stop paying attention. Security monitoring has moved beyond looking only for known fingerprints: it also measures deviation from normal behaviour to find patterns that have not been seen before. Maritime monitoring has a related challenge, but the sea is unpredictable and a single vessel at a single moment can easily look unusual.

ALIBI applies a security-engineering principle to maritime data: **do not only raise suspicion; test the evidence that could explain it.** Existing AIS tools can provide the initial list of unusual movements. ALIBI adds context and reduces that list, rather than trying to replace those tools or duplicate their entire feature set.

The guiding principle is that everyone is innocent until proven otherwise. In the spirit of *ei incumbit probatio qui dicit, non qui negat*, ALIBI reports evidence and uncertainty; it does not make accusations. An unexplained event is a reason to look more closely, not proof of intent.

## Product boundary: the product versus the demo

### The product

The product is a source-agnostic triage and enrichment service:

- Accept vessel tracks, events and contextual data from one or more upstream systems through defined APIs or adapters.
- Assess how unusual an event is against available baselines.
- Test possible explanations using independently sourced evidence.
- Produce a refined, prioritised list with separate unusualness and unexplainedness measures, confidence levels and traceable evidence.
- Expose results and evidence references through an API so an existing AIS or maritime monitoring product can display them in its own workflow.
- Allow data sources and scoring sensitivity to be configured, with the applied configuration and model version recorded for each assessment.

The upstream system may identify a slowdown, loitering, route deviation or another event. ALIBI does not need to own the original detection step in a production deployment. For the hackathon, however, the prototype needs a basic anomaly detector so the jury can see the whole process without access to a third-party AIS monitoring platform.

### The demo

The demo includes a small, built-in AIS anomaly view and a distinct analysis interface. This is demonstration scaffolding, not a claim that ALIBI should compete with established AIS monitoring products.

The interface should feel closer to an IT anomaly-detection console or scientific instrument than a conventional maritime traffic map. Use trend plots, expected-versus-observed behaviour, event timelines, factor contributions and source toggles. A map can provide geographic context, but it must not dominate the screen.

A game-like visual language can make the demo memorable and clearly signal that this is an experimental analysis layer. Keep the language responsible: use terms such as *unusual*, *explained*, *unexplained*, *confidence* and *evidence* rather than *guilty*, *hostile* or *threat detected*.

## Architecture: two separate products, one API

The prototype should be split from the start, even if both parts initially run on the same machine. This is a product boundary, not a deployment complication.

### 1. AIS tool: data and demonstration front end

The small AIS tool owns the live AIS feed, track display, replay controls and basic anomaly detection used to create candidate events for the hackathon. It is the test client and demonstration harness. Its detector exists so the end-to-end demo works without a third-party monitoring platform; it is not the core ALIBI product.

### 2. ALIBI backend: independent assessment service

The backend accepts a candidate event and the track/context required to assess it, enriches it with available evidence, and returns a structured assessment: unusualness and unexplainedness as separate measures, confidence, evidence factors, source attribution and limitations. It should not depend on the front end's internal state or require the front end to be running.

The browser interface is one client of the API, not the place where ALIBI's reasoning lives. The same API should be callable from a script, another AIS platform or a simple command-line request. As a practical demo test, stop the interface and submit a saved event directly to the backend. The assessment should still work and be inspectable as JSON.

### API-first integration

Define a small versioned REST API and document it with an OpenAPI specification that renders in Swagger UI. Keep the first contract deliberately small:

- `POST /api/v1/assessments` — submit an event, track observations and optional metadata; return an assessment or an assessment identifier.
- `GET /api/v1/assessments/{assessment_id}` — retrieve the result, evidence breakdown and recorded configuration.
- `GET /api/v1/health` — basic service health for the demo and deployment checks.
- `GET /api/v1/openapi.json` (or a hosted YAML file) — publish the machine-readable API contract.

Use a stable event schema with UTC timestamps, vessel identifiers where available, source references and explicit units. Return source-level findings and confidence rather than only a single score. Include the API version, assessment timestamp, sensitivity/configuration and model version in every result. Define clear validation errors and distinguish unavailable source data from evidence that actively supports or weakens an explanation. The first implementation can be synchronous; asynchronous jobs can wait until processing time or volume justifies them.

A small OpenAPI/Swagger document is part of the useful product boundary, not merely presentation material: it lets a potential integrator understand the request and response without reading the front-end code. The hackathon need only implement the endpoints exercised by the demo.

### Public API and deployment

The data sources are largely open, so a public API is a plausible next step. Open data does not automatically mean unrestricted redistribution or unlimited compute, however. Before opening the service to general use, check each source's licence and attribution requirements, avoid exposing data that should not be republished, and add sensible request limits, timeouts, payload limits, caching and basic abuse protection. Start with a documented API that can be accessed by the demo; decide whether it is anonymous, key-based or rate-limited before making a public commitment.

The intended hosting options are the user's lab server at **helppox.com** or production server at **apn201.com**, both with Apache available. Apache can terminate HTTPS and reverse-proxy requests to the separately running ALIBI service; keep the API process isolated from the web server and do not make the API's public exposure depend on the demo UI. The target host is not yet decided. The initial deployment should favour a small, repeatable service with logs, a health check and a clear way to restart it.

## Core workflow

1. **Find an unusual event.** For the demo, ALIBI uses a simple baseline detector over AIS history to create candidate events. In the intended product, an upstream monitoring tool can provide these candidates.
2. **Build the context.** Join the event with the available vessel history, environmental conditions, location, surrounding traffic, position quality and relevant external records.
3. **Test explanations.** Evaluate which sources support, weaken or do not affect a possible explanation. Copernicus Marine data is a central hypothesis to test, not merely a visual layer.
4. **Refine the list.** Keep the original unusualness assessment separate from the unexplained component. Rank or filter candidates according to configurable sensitivity; do not silently erase the underlying evidence.
5. **Drill down.** Let an analyst inspect the score, contributing factors, source data, timestamps, confidence, missing data and model/configuration version.
6. **Export or integrate.** Provide the assessed events in a machine-readable form suitable for downstream systems. The hackathon can demonstrate this with a local API or a documented JSON output if a full integration is out of scope.

## Functional requirements

### Must have

- **Reproducible AIS replay:** Replay selected real tracks from the recorded AIS data. Use fixed, known cases so the demo does not depend on live traffic producing an interesting event at the right moment. The live product can remain available to judges as a secondary exploration option.
- **End-to-end demo detection:** A simple detector in the separate AIS tool creates the initial unusual-event list, clearly labelled as demo functionality.
- **Separate service boundary:** The AIS tool calls the ALIBI backend over a versioned HTTP API; ALIBI assessment logic must run without the UI. Demonstrate this by submitting at least one saved event directly to the API.
- **API contract:** Provide an OpenAPI/Swagger document and implement the assessment request, assessment result and health endpoints used by the demo.
- **Separate measures:** Show *Unusual* and *Unexplained* as distinct measures. The first represents deviation from the baseline; the second represents the deviation that available evidence has not explained. Do not collapse them into one opaque risk score.
- **Copernicus Marine integration:** Join appropriate environmental data to AIS events and show the result of including or excluding it.
- **Source on/off analysis:** Allow individual data sources to be enabled or disabled and rerun the same cases. Display the before-and-after results so the contribution of Copernicus and other sources can be examined rather than assumed.
- **Sensitivity control:** Let the user tune the threshold or sensitivity and see how the candidate list changes. Record the selected setting with the results.
- **Evidence drill-down:** For each event, show the observed-versus-expected trend, relevant time and location, contributing factors, source attribution, timestamps, confidence, data gaps and why a factor did or did not explain the behaviour.
- **Auditability:** Keep a traceable record of inputs or source references, transformations, enabled sources, thresholds, model/configuration version and resulting scores. Audit details belong in the drill-down, not on the main dashboard.
- **External enrichment:** Include the planned sanctions and GUR listings as separate, source-attributed identity/context signals. They do not explain vessel behaviour and must not, by themselves, make behaviour more or less explained. Preserve the distinction between a legal sanctions designation and another organisation’s listing or assessment.
- **Responsible language:** State clearly that unexplained behaviour does not establish malicious intent. Missing data or poor position quality should reduce confidence rather than automatically increase suspicion.
- **Known-case evaluation:** Include the Eagle S replay and at least one contrasting fleet-slowdown case. Report the actual measured outcome, not a preselected success claim.
- **Clear limits and attribution:** Document the receiver coverage, historical period, source limitations, model assumptions and data licences/attributions.

### Nice to have

- A compact, interactive anomaly timeline and trend plots for multiple vessels.
- A restrained geographic view for route, anchorage, port approach and cable-corridor context.
- Vessel-type prototypes, individual vessel profiles and journey-level baselines, with visible cold-start confidence.
- Working-vessel context for tugs, pilot boats, SAR, law enforcement and other classes whose normal behaviour differs from cargo traffic.
- Position-quality context using AIS fields such as `posAcc` and `raim`, once their reliability is assessed.
- More complete API capabilities such as asynchronous assessments, batch submissions, API keys and usage metrics, if justified by the prototype.
- Public API access after data licences, attribution, rate limits and abuse protection have been reviewed.
- Live AIS scoring as a secondary mode, after the recorded replay and analysis are reliable.
- White-space analysis showing where a vessel type has not been observed, carefully distinguishing lack of coverage from absence of traffic.

## Data sources and their roles

ALIBI is designed to accept multiple inputs; the hackathon uses the sources that can be integrated within the available time. The source list is not the product boundary.

| Source | Role in the prototype | Important distinction |
|---|---|---|
| AIS from Fintraffic Digitraffic and recorded history | Tracks, metadata, baseline and replay | Receiver coverage is regional, not all of the Baltic |
| Copernicus Marine physics | Currents, sea level and ice where relevant | Use the physical variables appropriate to the question |
| Copernicus Marine waves | Wave conditions for the event and location | Correlation with slowdown is not proof of causation |
| Wind source selected for the event | Environmental context | Verify product, units, coverage and licence before use |
| Location/context layers | Anchorages, approaches, pilot areas and infrastructure corridors | Context can explain ordinary behaviour or make an event worth reviewing; it does not prove intent |
| EU sanctions list | Identity/context enrichment by a reliable vessel identifier | A designation is not an explanation of behaviour |
| GUR / War & Sanctions listing | Separately labelled external assessment and its stated source/reason | Do not label it “sanctioned” unless that is legally accurate |
| AIS position-quality fields | Evidence quality and confidence | Poor quality should weaken confidence, not automatically raise the anomaly score |
| Historical incident material, including Eagle S | Evaluation of the method | Respect source terms; do not redistribute data without permission |

All sources should have clear attribution. External identity lists are enrichment signals, not substitutes for behavioural analysis.

## Analysis and proof of value

The central hypothesis is: **adding Copernicus Marine data can improve the usefulness of the unusual-event list by explaining some slowdowns that AIS-only analysis cannot explain.** This must be tested and shown in the pitch.

Use fixed replay cases, the same AIS baseline and the same sensitivity setting for comparisons. Run at least:

1. AIS baseline only.
2. AIS plus Copernicus Marine conditions.
3. AIS plus Copernicus and the other available contextual sources.
4. A sensitivity comparison showing the trade-off between earlier detection and the number of candidates.

For each run, report the number of candidates, which cases move in the ranking or change assessment, what evidence caused the change, and what remains unexplained. Include a case where environmental data helps explain a fleet slowdown and a contrasting case where it does not adequately explain the observed behaviour. If the results do not support the hypothesis, report that honestly.

The preliminary Eagle S replay in the project notes suggests that a sensitive slowdown rule may identify the slowdown earlier than a conservative rule, at the cost of more false positives. Treat the reported figures as preliminary until rerun against the final event build and documented evaluation procedure. Do not tune only to Eagle S.

## Interface principles

- **Analysis first, map second.** Prioritise trends, deviations, evidence and confidence. Geographic context is available when it helps explain an event.
- **A list to investigate, not a list of villains.** The primary output is a manageable, configurable queue of unusual events that remain insufficiently explained.
- **Reveal complexity on demand.** The main screen shows the pattern and the assessment. Drill-down shows the factor-level evidence and audit trail.
- **Make uncertainty visible.** Distinguish low confidence, missing data and an evidence-backed unexplained deviation.
- **Make comparisons easy.** Source toggles and sensitivity controls must support repeatable before-and-after analysis.
- **Distinctive but not misleading.** The game-like/scientific-instrument visual design separates the hackathon mockup from established AIS interfaces. It is not intended to imply that a production service would replace those interfaces.

## Technical shape

- **AIS tool:** a separate front-end/test client that owns live AIS ingestion, track/replay presentation and the basic demo anomaly detector.
- **ALIBI service:** a separate backend that owns enrichment, explanation, scoring, confidence and evidence output. It must not depend on front-end state.
- **API contract:** versioned REST/JSON endpoints documented with OpenAPI and viewable through Swagger UI; the interface is only one API client.
- **Ingestion:** adapters for AIS/event inputs and contextual sources; APIs are the intended integration boundary.
- **Recorder and replay:** append-only AIS capture with gap logging and integrity verification; deterministic replay of selected tracks for the demo.
- **Analysis:** Python pipeline for track preparation, baselines, environmental joins, factor evaluation, confidence and sensitivity.
- **Evidence ledger:** retain event-level facts and source references separately from the computed score so scores can be recalculated as models or weights change.
- **Configuration:** explicit source enablement, thresholds and model version; every result records the configuration used.
- **Presentation:** a lightweight browser UI with trend plots, factor breakdown, source toggles and a secondary geographic view.
- **Output:** a small, documented JSON/API contract for assessed events and evidence references. A production integration is a future step, not a hackathon dependency.
- **Deployment:** deploy the backend independently behind Apache HTTPS/reverse proxy on either helppox.com (lab) or apn201.com (production); select the host later. Keep public exposure, source licences, rate limiting and basic abuse protection as explicit deployment decisions.
- **Operations:** reliable local replay and saved results first; live scoring is optional. Do not make the demo depend on continuous connectivity or a live event occurring.

## Out of scope for this hackathon

- Replacing an existing AIS monitoring or maritime domain awareness platform.
- Proving hostile intent, declaring sabotage or automatically issuing operational alerts.
- A production-grade integration with a commercial AIS platform.
- A public, unrestricted production API before source terms, operating limits and abuse controls have been reviewed.
- A fully calibrated, long-term vessel-history risk model.
- Claiming general detection accuracy from one incident or a few weeks of regional data.
- Inferring an invisible second vessel or covert boarding from insufficient AIS evidence.

## Pitch message

**ALIBI does not try to find guilty ships. It helps maritime monitoring systems spend attention where the available evidence cannot explain what a ship is doing.**

The demo shows both sides of the method: an anomaly whose assessment changes when environmental evidence is added, and a case that remains unexplained. The audience can switch sources, adjust sensitivity and inspect why the result changed. Copernicus Marine data earns its place by changing the analysis, not by decorating the map.

ALIBI is an early prototype built by a solo engineer with a security-monitoring background. The next step is to validate the method with maritime domain experts and determine whether the reduction in unexplained candidates materially improves analyst triage.

*The sea is the alibi. The unexplained is what deserves a closer look.*
