# Proof of value (sensitivity 0.5)

| case | detector alone | top band, AIS-only | + Copernicus | + everything |
|---|---|---|---|---|
| Eagle S, 25 Dec 2024: speed drop towards Estlink 2 | 2 | 1 | 1 | 1 |
| TERRY, Oresund, 22 Mar 2012: grounding pattern | 1 | 1 | 1 | 1 |
| Gulf of Finland fleet slowdown, 5-6 Oct 2026 | 211 | 53 | 49 | 49 |
| Danish waters fleet slowdown, 3-6 Oct 2025 (widest) | 60 | 16 | 14 | 14 |
| Danish waters fleet slowdown, 1-7 Feb 2026 | 60 | 13 | 9 | 9 |
| Danish waters fleet slowdown, 2-4 Jul 2026 (counter-example) | 60 | 13 | 11 | 11 |
| Recorded day 2026-10-25: every candidate | 126 | 25 | 21 | 21 |
| Recorded day 2026-10-26: every candidate | 138 | 23 | 20 | 20 |
| Recorded day 2026-10-27: every candidate | 124 | 25 | 25 | 25 |
| Recorded day 2026-10-28: every candidate | 115 | 21 | 20 | 20 |

## Sensitivity sweep, everything on

| case | s=0.0 | s=0.25 | s=0.5 | s=0.75 | s=1.0 |
|---|---|---|---|---|---|
| Eagle S, 25 Dec 2024: speed drop towards Estlink 2 | 1 / 0 | 1 / 1 | 2 / 1 | 2 / 2 | 2 / 2 |
| TERRY, Oresund, 22 Mar 2012: grounding pattern | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 |
| Gulf of Finland fleet slowdown, 5-6 Oct 2026 | 98 / 25 | 98 / 29 | 211 / 49 | 211 / 52 | 344 / 72 |
| Danish waters fleet slowdown, 3-6 Oct 2025 (widest) | 60 / 6 | 60 / 14 | 60 / 14 | 60 / 14 | 60 / 16 |
| Danish waters fleet slowdown, 1-7 Feb 2026 | 60 / 7 | 60 / 9 | 60 / 9 | 60 / 10 | 60 / 12 |
| Danish waters fleet slowdown, 2-4 Jul 2026 (counter-example) | 60 / 8 | 60 / 10 | 60 / 11 | 60 / 12 | 60 / 13 |
| Recorded day 2026-10-25: every candidate | 55 / 3 | 55 / 5 | 126 / 21 | 126 / 26 | 200 / 27 |
| Recorded day 2026-10-26: every candidate | 67 / 11 | 67 / 12 | 138 / 20 | 138 / 22 | 200 / 25 |
| Recorded day 2026-10-27: every candidate | 56 / 12 | 56 / 15 | 124 / 25 | 124 / 27 | 200 / 31 |
| Recorded day 2026-10-28: every candidate | 54 / 7 | 54 / 14 | 115 / 20 | 115 / 23 | 200 / 27 |

Cells: detector candidates / top band.

## Gulf of Finland fleet slowdown, 5-6 Oct 2026: moved by Copernicus

- AURELIE slowdown 2026-10-05T18:06:00Z: 0.5097 -> 0.0267. The sea can account for about 95 % of the slowdown: wind 12.5 m/s from the south-west, waves 2.5 m, current -0.1 kn along the course.
- DSM FERRO slowdown 2026-10-05T20:31:00Z: 0.5087 -> 0.4758. 
- THEIA slowdown 2026-10-06T00:27:00Z: 0.8671 -> 0.197. The sea can account for about 77 % of the slowdown: wind 14.5 m/s from the south-west, waves 3.4 m, current -0.4 kn along the course.
- KERTU slowdown 2026-10-06T11:21:00Z: 0.5629 -> 0.4606. 

## Danish waters fleet slowdown, 3-6 Oct 2025 (widest): moved by Copernicus

- SKORPION slowdown 2025-10-04T00:00:00Z: 0.5105 -> 0.2718. The sea can account for about 47 % of the slowdown: wind 14.1 m/s from the south, waves 2.3 m, current -0.1 kn along the course. Ships of this kind usually run at 8.9 kn in this area, below their class's typical 10.7 kn (49 passages).
- BERNHARD slowdown 2025-10-04T06:53:00Z: 0.7268 -> 0.3153. The sea can account for about 57 % of the slowdown: wind 18.6 m/s from the south, waves 3.3 m, current -0.2 kn along the course. Ships of this kind usually run at 9.8 kn in this area, below their class's typical 11.8 kn (31 passages).

## Danish waters fleet slowdown, 1-7 Feb 2026: moved by Copernicus

- KARIN LEHMANN slowdown 2026-02-02T01:59:00Z: 0.9989 -> 0.3373. The sea can account for about 66 % of the slowdown: wind 14.0 m/s from the east, waves 2.3 m, current -0.3 kn along the course.
- CGAS MAUD slowdown 2026-02-03T02:53:00Z: 0.7702 -> 0.2962. The sea can account for about 62 % of the slowdown: wind 14.9 m/s from the east, waves 2.8 m, current -0.3 kn along the course.
- KOBE PIONIER slowdown 2026-02-04T04:50:00Z: 0.9594 -> 0.123. The sea can account for about 87 % of the slowdown: wind 15.4 m/s from the east, waves 2.7 m, current -0.5 kn along the course.
- GRIFTBOR slowdown 2026-02-04T12:24:00Z: 0.9855 -> 0.178. The sea can account for about 82 % of the slowdown: wind 15.5 m/s from the east, waves 2.8 m, current -0.4 kn along the course.

## Danish waters fleet slowdown, 2-4 Jul 2026 (counter-example): moved by Copernicus

- RIX GULF slowdown 2026-07-02T19:17:00Z: 0.6605 -> 0.0. The sea can account for about 100 % of the slowdown: wind 14.7 m/s from the west, waves 2.2 m, current -0.1 kn along the course.
- HAAFJELL slowdown 2026-07-03T01:45:00Z: 0.5733 -> 0.0. The sea can account for about 100 % of the slowdown: wind 13.9 m/s from the west, waves 2.0 m, current -0.8 kn along the course. The 10 other ships within 25 km were also running 11 % below their usual speed at the time.

## Recorded day 2026-10-25: every candidate: moved by Copernicus

- STAV VIKING slowdown 2026-10-25T01:50:00Z: 0.5956 -> 0.4929. 
- AMALIE ESSBERGER slowdown 2026-10-25T07:20:00Z: 0.6742 -> 0.4757. The sea can account for about 29 % of the slowdown: wind 10.0 m/s from the south, waves 1.1 m, current -0.2 kn along the course.
- SILJA SYMPHONY slowdown 2026-10-25T19:42:00Z: 0.5195 -> 0.4417. 
- DRINA S slowdown 2026-10-25T22:41:00Z: 0.5756 -> 0.4184. The sea can account for about 27 % of the slowdown: wind 14.3 m/s from the south, waves 3.3 m, current -0.2 kn along the course. The 7 other ships within 25 km were also running 7 % below their usual speed at the time.

## Recorded day 2026-10-26: every candidate: moved by Copernicus

- ECO MISTRAL slowdown 2026-10-26T01:17:00Z: 0.5132 -> 0.4577. The 9 other ships within 25 km were also running 6 % below their usual speed at the time.
- ALMA slowdown 2026-10-26T13:35:00Z: 0.6414 -> 0.2509. The sea can account for about 61 % of the slowdown: wind 12.5 m/s from the south, waves 2.7 m, current -0.3 kn along the course.
- KARIN LEHMANN slowdown 2026-10-26T23:52:00Z: 0.7011 -> 0.2712. The sea can account for about 61 % of the slowdown: wind 11.7 m/s from the south-west, waves 2.4 m, current -0.2 kn along the course.

## Recorded day 2026-10-28: every candidate: moved by Copernicus

- ICELAND slowdown 2026-10-28T15:05:00Z: 0.5303 -> 0.3417. The sea can account for about 36 % of the slowdown: wind 10.2 m/s from the south, waves 1.3 m, current -0.0 kn along the course.
