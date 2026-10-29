# ALIBI

ALIBI (Automatic Lookout for Irregular Baltic Itineraries). Copernicus Marine Service Hackathon 2026, challenge Enhancing Maritime Security and Resilience. Solo entry by Juha Lilja (APN201).

Repo: https://github.com/apn201/Alibi | Demo: https://helppox.com/alibi/ | API docs: https://helppox.com/alibi/api/v1/docs

## Why

I decided to build for the marine security track, to see if there is something I can bring from my experience as an IT security director.

False positives are a problem. They undermine the credibility of any dashboard and in the end you stop reading it. To tell what is suspicious, you first need a baseline of what is normal. In the past antivirus tools looked for fingerprints of malicious processes. That only revealed known viruses. Nowadays the systems measure deviation from "normal", so they also detect new and unknown patterns. So can this be used in maritime security? Can we combine weak signals into something useful?

The obvious topic for me was anchor dragging and other possible hybrid threats to marine traffic, which have grown with the current political situation.

I'm not the first. There are tools that monitor AIS data and try to flag suspicious activity. But like the old antivirus, they assume we know all the things to look for. They do simple correlations, like: does AIS report "anchored" with speed above 0? That flags dozens of ships "dragging anchors". Or: is the ship on a sanctions list? That alone says nothing about what the ship is doing. The weak signals must be combined to build the real picture.

The sea is unpredictable. One vessel at one moment will often look suspicious. The idea of ALIBI is to combine the weak signals to explain the unexpected behaviour. So instead of concentrating on red flags, we concentrate on the things that explain them. The unexplained is the interesting batch.

My hypothesis is that a lot of "strange" behaviour can be explained by weather. That is my angle on Copernicus data: to see if the weather and other information can explain the behaviour.

Copernicus data alone does not explain everything, so ALIBI collects weak signals from several sources and combines them. Open data explains the location and the vessel: restriction areas, anchoring bans, cable signs, fairways. (A list of shipwrecks was planned too, not built yet.) Loitering near a cable can be explained, or it can raise the question. Either way. From AIS data we build behaviour profiles for types of ships and for individual vessels, in relation to the place and the weather. Live AIS is interesting too: all ships slowing down at once can be a sign of bad weather, and we can see if Copernicus supports it.

All this needs a lot of data. The patterns are built from historical data. For weather the history is available, but for Baltic AIS there is only live data. Luckily Denmark publishes its AIS history as open data. It is a treasure trove, as most ships in the Baltic pass Danish waters. So in a short build time we could build a lot of patterns from the historic AIS data and test the hypothesis about the impact of weather (for example by combing the data for events where everyone slowed down). The profiles keep improving from live data. As it is a lot of data, the raw data is purged once processed; the profiles keep what was learned. For unexplained cases the raw data could be kept a bit longer.

Knowledge is power (although some in Finland say "tieto lisää tuskaa", knowledge adds pain, which is especially funny because of the large IT provider called Tieto).

In short: we monitor everything, we find unusual patterns and try to explain them, and we measure how well that works. Everyone is innocent until proven otherwise. Right of innocent passage etc.

*Ei incumbit probatio qui dicit, non qui negat.* We are not the ones to prove anything. We just process the information and show it.

## What it does

ALIBI is middleware, not another AIS map. An existing AIS system flags something unusual and calls the ALIBI API with the event and the ship's track. ALIBI answers with two numbers, Unusual and Unexplained, plus confidence and one finding per source: the sea (Copernicus Marine waves, currents, wind and ice), the place, the ship's own habits, the traffic around it, navigational warnings and position quality. Sanctions and the GUR listing are shown as identity context and never change the score. Every answer records the versions and settings it was made with, and goes to an audit ledger.

For the demo I needed something to raise the flags, so there is a small detector too. It does what simple tools do: slowdowns, the Eagle S pattern, grounding pattern, AIS gaps, slow passage over cables. It over-flags on purpose. The GUI is a console where you switch sources on and off and move the sensitivity, and see the list change.

## Did it work

First the hypothesis. I compared 47,893 moving segments of merchant ships with each ship's own usual speed and with Copernicus wind and waves at that time and place. In calm sea 15 % of them were clearly slow (below 85 % of own speed). At 14 m/s wind or more it was 48 %, at 2.5 m waves 51 %. So the weather explains a lot. Correlation, not proof.

Then the list. On an ordinary recorded day the detector raised about 126 candidates. ALIBI left about 22 of them in the top band. Most of that came from the place and the ship's own habits (arrivals, anchorages), not from Copernicus. Copernicus does its part on stormy days: 10 to 30 % fewer in the top band, and single ships drop from "unexplained" to "explained" (one went from 0.87 to 0.20 with 14.5 m/s wind and 3.4 m waves). On calm days it changes almost nothing, which is how it should be.

Eagle S stays unexplained. The sea accounts for about 0.1 kn of its 3.7 kn drop. With the sensitive rule the detector flags it 8 minutes after the drop began, before Estlink 2. The conservative rule takes 59 minutes. So the idea is a sensitive detector, and ALIBI to make its noise affordable.

22 a day is still more than I wanted. The rest are mostly ships slowing for hours, probably timing their arrival. Nothing in my sources explains that yet.

I also checked if Copernicus data could show ships with the transponder off. It cannot: the Copernicus Marine products are km-scale and have no ships in them. Sentinel-1 radar can, and there was no Sentinel-1 pass over the Gulf of Finland at the time of Eagle S. Details in [dark-vessels-feasibility.md](dark-vessels-feasibility.md).

## Built before and during

Before the event: the AIS recorder (running since 4 Oct), the profile research and the plan. During the event: everything else, including all Copernicus work. See [PRIOR_WORK.md](../PRIOR_WORK.md).

## Limits

No live alerts, ranking only. Unexplained is not evidence of anything. The thresholds rest on few real cases. Our own AIS covers Finnish waters from 5 Oct 2026, the Danish archive from Oct 2024. Copernicus fields are hourly and about 2 km. Full list in the [README](../README.md#limits).
