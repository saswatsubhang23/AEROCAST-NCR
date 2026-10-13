# Where the data comes from, and how far to trust it

> A live audit of the three sources the application relies on (Open-Meteo with CAMS, OpenAQ, and the xKDR archive), run on 11 October 2026. Every figure below was observed in a response on that day; where a fact could not be verified it says so. The audit found a six-hour timestamp error in one source, which has been fixed.

## The short version

| Source | What it gives | Newest data | Resolution | Main caveat |
|---|---|---|---|---|
| Open-Meteo forecast | Weather: wind, rain, temperature, boundary-layer height, radiation, winds up to 3 km | now, to 16 days ahead | cells about 8 × 10 km | Model output, never a measurement |
| Open-Meteo archive | The same, as historical analysis, from 1940 | about 23 hours ago | 9 km (IFS) / 0.25° (ERA5) | One-day lag |
| CAMS via Open-Meteo | Modelled PM2.5, PM10, NO₂, SO₂, O₃, CO, NO, dust, AOD | now, to 7 days ahead | **cells about 0.4° (44 km)** | A model; on Delhi stations worse than "same hour yesterday" |
| OpenAQ | Hourly station observations, 115 monitors in NCR | **median 80 hours ago**; 1 of 113 within 3 hours | points | Feed lags by days; licences mostly unstated |
| xKDR archive | CPCB and US Embassy hourly history, 2009 onward | CPCB: 1 Sep 2025; US Embassy: 27 Mar 2026 | points | Timestamp convention differs by source |

The two sentences that matter most: **there is no live ground truth for Delhi at the moment** (the observation feed trails the present by more than three days), and **the only current pollutant field is a coarse model**. Everything the application shows as "now" is therefore either a replay, a model, or a simulation, and each is labelled as such.

## Open-Meteo: weather

The forecast endpoint returned 552 hourly rows for a request of seven past days and sixteen forecast days, with no missing values in ten variables. It accepts up to sixteen days ahead (seventeen is refused with HTTP 400) and more than ninety days of past data. A request for Delhi was snapped to the grid point at 28.576° N, 77.187° E at 214 m elevation, and probing at 0.02° spacing shows the native cells are about 0.070° tall and 0.103° wide (8 × 10 km). Wind speed is returned in km/h unless metres per second are requested, and the application asks for metres per second throughout; conversions are recorded rather than silent.

The archive reaches back to 1940 and its newest hour was 23 hours old. Neither endpoint returns rate-limit headers, so the limit can only be seen by hitting it. Open-Meteo's published free allowance is 600 calls a minute, 5,000 an hour and 10,000 a day for non-commercial use; in practice, bursts of archive requests during the evaluation of the coupled model were refused and needed spacing and a retry. Licence: the data are CC BY 4.0, the free service is non-commercial, and commercial use needs a subscription.

The application also reads winds at 80, 120 and 180 m and on the 925, 850 and 700 hPa surfaces (about 0.8, 1.5 and 3.2 km above ground), which is what makes the vertical structure of the 3D flow real rather than decorative.

## CAMS: the only current pollutant field

Open-Meteo serves CAMS global composition forecasts. A 92-day past window plus seven days ahead was returned with 1.5 % missing values; eight days ahead is refused. Units are µg/m³ (aerosol optical depth is dimensionless). Stepping 0.05° at a time across 1.1° of longitude gave only three distinct values, changing at 77.0° and 77.4°, so the effective cell is **0.4° or about 44 km** and Delhi-NCR holds only about nine cells. This is why the live field on the Air Flow page is made of large blocks, and why no city-scale structure should be read into it.

How good is it at the stations? For the 60 days ending 9 October 2026 (the newest stored hour), CAMS at 60 stations' coordinates was compared with the station hourly values, at the best of a few time shifts:

| Pollutant | Obs. mean (µg/m³) | CAMS bias | CAMS MAE | Same hour yesterday MAE | Hour-of-day mean MAE | Correlation |
|---|---:|---:|---:|---:|---:|---:|
| PM2.5 | 43 | +20 | 30.0 | 18.5 | 19.3 | 0.29 |
| PM10 | 116 | +34 | 91.7 | 43.3 | 48.9 | 0.26 |
| NO₂ | 52 | −19 | 31.5 | 15.3 | 15.9 | 0.23 |
| O₃ | 24 | +71 | 73.1 | 7.9 | 9.2 | 0.44 |
| SO₂ | 31 | −6 | 18.9 | 8.8 | 10.8 | 0.02 |

CAMS is a poor predictor of an individual Delhi station here: for every pollutant it is further from the observation than repeating yesterday's value, and its correlation is low. Two cautions. This compares the model's current estimate for past hours, not a forecast issued a day earlier. And the large ozone bias deserves a unit and siting check before it is read as a model error alone (stations near traffic destroy ozone that a 44 km cell cannot see). The finding that matters for design is the first one: a raw CAMS value is not a substitute for a station forecast, which is why a local model is justified.

## OpenAQ: the observations

OpenAQ's version 3 API requires a key, allows 60 requests a minute (the response headers say so: limit 60, remaining counted down), and returned 115 reference-grade monitors inside the NCR box, 82 from CPCB, 30 from the CAAQM network and a handful from AirNow and the State Air programme. Each location lists its sensors with parameters and units.

The audit found three things worth knowing. **Freshness is poor:** the time since each location's last datum had a median of about 80 hours; one location was within three hours and 24 hours; 39 of 113 had not reported for more than a week, some for years. **Licences are mostly unstated:** one location listed a licence (US Public Domain); 114 listed none, so redistribution terms cannot be assumed and the application shows OpenAQ's attribution. **Units are mixed:** gases arrive as ppb, ppm or µg/m³, depending on the sensor, which is why every value is converted with a documented factor (25 °C, 1 atm) and keeps its original value and unit beside it.

OpenAQ also carries NO, NOx, temperature, relative humidity, wind speed and wind direction on CPCB stations. None of these is ingested yet. That corrects an earlier statement in this project that nitrogen oxide and station weather were unavailable: they are available, from a feed already in use.

The hourly-values response has `value`, a `period` with UTC and local start and end, a `coverage` block (expected and observed counts and percentage), and `flagInfo`. Periods are labelled as the provider gives them; for CPCB stations they end at the top of the Indian hour, which is why their UTC times fall on the half hour.

## xKDR: the long history, and a six-hour error

The xKDR archive holds 196.5 million hourly rows from 558 stations since January 2009, 72 of them inside the NCR box, exported on 30 September 2026. It is a history, not a feed: CPCB stations in Delhi-NCR end on 1 September 2025, and only the US Embassy monitor continues, to 27 March 2026. Its metadata says timestamps are naive Indian Standard Time.

The audit tested that claim against the one station that both xKDR and OpenAQ serve over the same months. Over 1,306 overlapping hours the two series are **identical** (correlation 1.000, mean absolute difference 0.0 µg/m³), but only when xKDR's times are shifted by six hours relative to how the application had been reading them. A physical check agrees: read as IST, the Embassy series has its daily minimum at 10:00, when the afternoon boundary layer should make it 16:00 to 17:00; read as UTC it falls where it should. The other xKDR stations are correct as documented: across 40 CPCB stations the median daily minimum falls at 17:00 in the xKDR period and 16:00 in the OpenAQ period.

So the US Embassy rows are in UTC and the rest in IST. The ingest now reads that source as UTC, a regression test pins the behaviour, and the affected station (OpenAQ id 8118, the one the live forecast was served from) was re-ingested and cleaned: its daily minimum moved from 11:00 to 17:00. The previous raw rows are backed up. **The trained model predates this fix, so retraining is recommended** (it is a button on the Model Training page; nothing was retrained here).

## Quality flags and the stored record

Every stored value keeps its original value and unit, the converted value, and a list of flags: low coverage, unit converted, unit suspect, out of range, flat-lined, sensor conflict, revised, and others. Values that fail a physical-plausibility check are kept and flagged, not clipped or dropped. Carbon monoxide is excluded entirely because every CO sensor in the window is labelled ppb with a median near 1, which is physically impossible; the labels, not the air, are wrong.

A single typed record now describes every value the application handles: its kind (observation, forecast, analysis, interpolation or simulation), the exact period it describes in UTC, when it was issued and retrieved, the station or the model cell and its size, original and standard units, flags, licence and attribution. The kind is part of a record's identity, so an interpolated value can never overwrite a measured one. The database section of the engineering report has the schema.

## What this means in practice

For "what is the air like right now", the CAMS model is the only current source and is labelled as a model. For "what did the monitors read", the store is accurate but days old. For "what will this monitor read", the trained model needs fresh observations the feed does not currently supply, which is why it declines to forecast for the present. Closing these gaps does not need a new model: it needs a fresher observation feed (or direct CPCB access), the NO/NOx and station-weather parameters that OpenAQ already offers, and a retraining after the timestamp repair.
