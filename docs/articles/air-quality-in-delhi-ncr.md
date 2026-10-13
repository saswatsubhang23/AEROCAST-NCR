# How the air of Delhi-NCR works, and how to read this application

> Pollution in Delhi-NCR is not a single number. It is a field that the weather stirs, stacks up and sweeps away, and this application tries to show that field moving. This report explains the physical picture, what each page shows of it, and what it cannot yet see.

## Four ideas that explain most of what you see

**Pollutants differ in where they come from and how they behave.** Fine particles (PM2.5) are small enough to travel hundreds of kilometres and to reach deep into the lungs; they come from combustion, from dust that has been ground fine, and from gases that turn into particles in the air. Coarse particles (PM10 minus PM2.5) are mostly dust and settle out within a day or so. Nitrogen dioxide (NO₂) is a combustion gas, strongest beside traffic and power plants. Ozone (O₃) is not emitted at all: it is made in sunlight from other pollutants, and it is *used up* where fresh nitrogen oxides are plentiful, so it is often lowest in the most polluted places. Sulphur dioxide (SO₂) comes from burning coal and oil and slowly becomes sulphate particles.

**The weather decides how much of an emission you breathe.** Emissions change slowly; concentrations change fast, because the volume of air they are mixed into changes. At night the air near the ground is a shallow, still layer and the same traffic and the same fires produce high concentrations. By mid-afternoon the sun has heated the ground, the mixing layer can be a kilometre or two deep, and the same emissions are spread through ten times the volume. This is why Delhi's PM2.5 almost always peaks in the early hours and falls to its daily minimum around 16:00 to 17:00, and why the *boundary-layer height* is one of the most useful numbers in the whole application.

**Wind moves pollution, and the region matters as much as the city.** Delhi sits at the south-western end of the Indo-Gangetic plain, a broad, flat basin that ventilates poorly. In October and November the winds turn north-westerly and smoke from crop burning in Punjab and Haryana arrives on them; in winter, calm and cold air under a temperature inversion lets everything accumulate for days; in the monsoon, rain washes particles out of the air and winds come in from the south-east. Dust from Rajasthan and the Thar arrives in the pre-monsoon months. A station reading is therefore the sum of what is local and what has been carried in.

**Chemistry connects the pollutants.** Sulphur dioxide and nitrogen oxides oxidise into sulphate and nitrate particles, so some of the PM2.5 you measure was a gas an hour or a day earlier. Ozone and nitrogen dioxide trade mass back and forth in sunlight. This is why the application can show a *combined* oxidant (Ox = O₃ + NO₂) that changes less than either does alone.

## What each page shows

The **Air Flow** page is the main picture. Particles are carried along by the weather model's wind; each is coloured by the concentration of the air it is in, on the Central Pollution Control Board's index classes (green is good, dark red is severe). Underneath is a smooth concentration field. In 3D the same air moves at seven model heights from 10 m to about 3 km over real terrain. If you switch the source to *Stored replay* you see the last 72 hours of station observations; *Live model* shows the CAMS atmospheric model, which is the only source that is current; *Coupled model* carries a starting field forward with the weather and simple chemistry.

The **Analysis** tab is the workbench behind it: station observations hour by hour, the interpolation between stations with its measured error, weather-model fields, and simulations with adjustable wind and mixing. **Early warning** ranks every station by the trained model's forecast against a threshold and says how uncertain each forecast is. **Weather** and **Air Quality** hold the plain forecasts and the station tables. **Data & Models** says what data exists, what does not, and lets you train a new model; nothing trains unless you press the button.

## Where pollution is likely to increase next

There are three ways the application answers this, and they are deliberately kept apart because they have different strengths.

*A statistical forecast for each station.* A model trained on a year of hourly observations and weather predicts PM2.5, PM10, NO₂ and O₃ at +1, +6 and +24 hours. On a held-out period it was closer than simply repeating the last value in eleven of twelve cases, and clearly better at six hours (PM2.5 error 15 against 18 µg/m³). It does not beat that baseline for PM10 a day ahead, and the application says so wherever that forecast appears. This is the most reliable answer to "what will this monitor read", but it needs fresh observations, and the station feed is currently days behind.

*A physical picture of where the observed air goes.* The transport and coupled models carry the current field with the wind and apply deposition, rain scavenging and sulphate formation. They show *where* polluted air is heading, which is exactly the question of regional movement. They have no emissions, so they cannot say where new pollution will appear, and on historical windows they did not beat simply holding the starting value. Read them as a picture of movement, not as a number to rely on.

*An independent atmospheric model.* CAMS (the Copernicus atmospheric composition service, reached through Open-Meteo) is a full chemistry model with emissions. It is updated every hour and covers the whole area, but its cells over Delhi are about 44 km across and, compared with the stations over the last two months, it was a worse predictor than "the same hour yesterday" (PM2.5 error 30 against 18.5 µg/m³; correlation 0.29). It is useful as regional context and as a check, not as a station forecast.

## Who is exposed

Exposure is concentration multiplied by the number of people breathing it, weighted towards the sensitive: children, the elderly, people in hospitals and schools. The application does not yet compute this, because the two layers it needs are not loaded: a gridded population (WorldPop or GHSL are free) and a list of hospitals, schools and care homes. The database schema already has tables for both, and the **Data Coverage** page lists them as obtainable. Until they are loaded, any map that claimed to show "who is affected" would be inventing it, so none does.

## How to read the colours and labels

Every layer carries a badge that says what kind of number it is. **Observed** is a measurement at a station. **Spatial estimate** is an interpolation between stations and is clear wherever fewer than two stations are within 12 km. **Weather forecast** and **Atmospheric model** are model output, not measurements. **Model forecast** is the trained model's prediction for one station. **Simulated** and **Hypothetical** are computed from assumptions, and scenarios are what-ifs rather than predictions. A **Stale** badge means the newest data are older than the limit; the application then describes the past and says so.

## What is missing

The honest list of absent data is on the **Data Coverage** page and in the data-sources report. The ones that matter most for the questions above are an emissions inventory, fire detections, nitrogen oxide and station-weather observations (offered by a feed already in use but not yet stored), vertical profiles of pollutants, and the population and sensitive-site layers. Several can be added without cost; the reports say how.
