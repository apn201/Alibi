# Can ALIBI find dark vessels from Copernicus data?

Date: 2026-10-29. Short answer: not from Copernicus Marine. Possibly from Sentinel-1 SAR, as a later step.

## 1. Copernicus Marine products cannot see single ships

Grid sizes of the Baltic products, against a ship of 100 to 250 m:

| Product | Resolution |
|---|---|
| [Baltic physics model](https://data.marine.copernicus.eu/product/BALTICSEA_ANALYSISFORECAST_PHY_003_006/description) | 1 nmi (about 1.85 km) |
| [Baltic wave model](https://data.marine.copernicus.eu/product/BALTICSEA_ANALYSISFORECAST_WAV_003_010/description) | 1 nmi |
| [Baltic ocean colour L3, OLCI](https://data.marine.copernicus.eu/product/OCEANCOLOUR_BAL_BGC_L3_NRT_009_131/description) | 300 m, daily |
| [Baltic SST L3S](https://data.marine.copernicus.eu/product/SST_BAL_SST_L3S_NRT_OBSERVATIONS_010_032/description) | 0.02 degrees (about 2 km), daily |
| [Global wind L4](https://data.marine.copernicus.eu/product/WIND_GLO_PHY_L4_NRT_012_004/description) | 0.125 degrees (about 14 km), hourly |

The two Baltic models contain no ships. They simulate water and waves, so a ship cannot show up in them. The satellite grids are 2 to 14 times coarser than a hull, or at best about the size of a hull (300 m), and they are daily composites. A wake is a few tens of metres wide. None of these products can show it.

One finer product exists. The [Baltic high-resolution ocean colour product](https://data.marine.copernicus.eu/product/OCEANCOLOUR_BAL_BGC_HR_L3_NRT_009_202/description) is built from Sentinel-2 at 100 m, daily, but only for a 20 km coastal strip. It is a [coastal water quality product (chlorophyll, turbidity, suspended matter)](https://help.marine.copernicus.eu/en/articles/5194057-ocean-colour-sentinel-2-high-resolution-products), resampled to 60 m and mosaicked. A big ship in shallow water could stir up sediment that shows as turbidity. I found no source that documents this for the Baltic, so I treat it as untested. It would also need a cloud-free day, and the strip does not cover the open Gulf of Finland cable corridors.

Verdict for part 1: no for the models, no in practice for the gridded satellite products.

## 2. Where ship detection does work in Copernicus

- **Sentinel-1 SAR.** Interferometric Wide mode gives a [250 km swath at about 5 x 20 m single-look](https://sentinel.esa.int/web/sentinel/user-guides/sentinel-1-sar/overview). It works at night and through cloud. Matching SAR detections against AIS is the standard dark-vessel method.
- **Detection limits.** A [Sentinel-1 and AIS matching study](https://sciwatch.kiost.ac.kr/handle/2020.kiost/45464?mode=full) matched 86.7 % of AIS ships but only 42 % of small ships. I found no single official minimum length. Treat vessels under about 20 m as unreliable.
- **EMSA.** [CleanSeaNet](https://www.interspill.org/downloads/archive/CleanSeaNet-10-years-S-Djavidnia-European-Maritime-Safety-Agency-EMSA.pdf) and the Copernicus Maritime Surveillance service give authorities vessel detections, mostly from Sentinel-1 (more than 85 % of images, per [EMSA](https://emsa.europa.eu/tags/download/6453/4322/23.html)). It is not open to us.
- **Global Fishing Watch.** [Paolo et al., Nature 2024](https://doi.org/10.1038/s41586-023-06825-8) used Sentinel-1 to find that 72 to 76 % of industrial fishing vessels are not publicly tracked, and 21 to 30 % of transport and energy vessels. Europe is a small share of the fishing result.
- **Sentinel-2 optical wakes.** Deep-learning wake detection at [10 m exists](https://www.iris.unina.it/handle/11588/911407). It needs daylight and clear sky. Baltic winter is a poor fit.
- **Constellation in 2026.** Sentinel-1A [ended operations on 30 June 2026](https://dataspace.copernicus.eu/node/4026). Sentinel-1C and 1D remain, and [1D became fully operational on 1 May 2026](https://starlust.org/sentinel-1-d-becomes-fully-operational-marking-major-milestone-in-europes-earth-observation-mission). The pair is [6-day repeat with a shifted pattern](https://dataspace.copernicus.eu/node/3949).
- **Access.** Catalogue search on the [CDSE](https://dataspace.copernicus.eu) OData endpoint worked anonymously from my machine (queries below). Downloads and processing need a free account.

## 3. Check: did a SAR image exist near the events?

Query: Sentinel-1 products whose footprint intersects the point 59.9 N 25.6 E, run 2026-10-29 against `https://catalogue.dataspace.copernicus.eu/odata/v1/Products`.

**24 to 26 Dec 2024 (Eagle S): no Sentinel-1 acquisition.** Nothing covered the point on those three days. With Sentinel-1B gone, only Sentinel-1A flew. The passes around it were 22 Dec 04:42 and 15:57 UTC, then 27 Dec 16:05 UTC. A SAR image at the slowdown (about 10:13 to 11:49 UTC on 25 Dec) did not exist. The case could not have been checked this way.

**20 to 28 Oct 2026: 7 passes** (GRD, IW, dual-pol), all about 04:3x to 04:4x or 15:47 to 16:05 UTC:
- 20 Oct 04:41 (S1D), 15:56 (S1D)
- 21 Oct 04:33 (S1C), 15:47 (S1C)
- 25 Oct 16:04 (S1D)
- 26 Oct 04:41 (S1C), 15:55 (S1C)

Nothing on 22 to 24 Oct or 27 to 28 Oct. The longest gap is 3.5 days (21 Oct 15:47 to 25 Oct 16:04). Late products can appear later, so 27 to 28 Oct may still fill in.

Reading: coverage over this point is two passes on some days and nothing on others, so many AIS gaps will have no image near them.

## 4. Verdict for ALIBI

**(a) Inside the hackathon: no.** It needs SAR processing, a new data source and an account, and the Copernicus Marine tie-in is absent.

**(b) Next step: a dark-target check explainer.** For an AIS gap or corridor event it would answer two questions. Did a SAR pass cover the area within about 30 to 60 minutes of the gap? Is there a detection without a matching AIS position within a distance tolerance? It needs:
- a CDSE account and the catalogue query above for coverage;
- either a CFAR detector (SNAP or pyroSAR), or GFW's published detections;
- AIS matching with time interpolation and a distance tolerance, since ships move during the 25 s of an image.

Expected limits: revisit gaps of hours to days, small boats missed, false detections from wind farms, islands, platforms and ice, and no answer at all when no pass exists. The most common honest output would be "no SAR image covers this".

**(c) Pitch sentence:** "ALIBI flags unexplained AIS behaviour; whether a ship went dark is a question for Sentinel-1 radar, which we show as the next step, not as something Copernicus Marine can see."

## What we can use now

Sea state does affect ships, which is ALIBI's sea_state explainer: waves from the [Baltic wave model](https://data.marine.copernicus.eu/product/BALTICSEA_ANALYSISFORECAST_WAV_003_010/description) explain slowdowns and drift. Fleet-wide behaviour compared with Copernicus fields is also valid. Ship detection is not.
