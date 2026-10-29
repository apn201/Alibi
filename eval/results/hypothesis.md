# Does the sea explain slowdowns?

47,893 moving segments of 3,957 merchant ships on the days the Copernicus cache holds.
Ratio = segment speed / the ship's own usual speed. Slow = below 85%.

Spearman correlation, ratio vs wind: -0.138; vs wave height: -0.111.

| sea | segments | median ratio | share slow |
|---|---|---|---|
| calm (wind < 5 m/s, Hs < 0.5 m) | 9,746 | 1.0 | 15.4% |
| rough (wind >= 11 m/s or Hs >= 1.5 m) | 12,211 | 0.955 | 30.4% |

| wind m/s | segments | median ratio | share slow |
|---|---|---|---|
| 0-5 | 10,699 | 1.0 | 15.3% |
| 5-8 | 13,600 | 0.99 | 17.8% |
| 8-11 | 13,354 | 0.981 | 20.4% |
| 11-14 | 8,109 | 0.962 | 27.5% |
| 14-40 | 2,131 | 0.873 | 47.7% |

| Hs m | segments | median ratio | share slow |
|---|---|---|---|
| 0-0.5 | 18,928 | 0.991 | 16.8% |
| 0.5-1 | 12,087 | 0.988 | 18.4% |
| 1-1.5 | 7,567 | 0.98 | 20.1% |
| 1.5-2.5 | 7,192 | 0.962 | 28.3% |
| 2.5-10 | 2,119 | 0.842 | 51.1% |
