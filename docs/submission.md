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

[proof section written after the measured runs]
