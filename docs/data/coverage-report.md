# Historical data coverage report

Generated 2026-10-10T06:24:50Z from `data\history.sqlite` (SQLite). Window: 2025-10-09T00:00:00Z to 2026-10-09T23:00:00Z (8784 hours). Every figure below is computed from the store; nothing is estimated.

Definitions: *active hours* are the hours inside the window during which the provider says a sensor existed (first to last datetime); *usable* hours carry no hard quality flag; coverage = usable / active. Months are IST months.

## Tables

| table | rows |
|---|---:|
| stations | 112 |
| sensors | 1,159 |
| raw_air | 13,152,889 |
| raw_weather | 3,324,746 |
| clean_air | 12,899,133 |
| clean_weather | 3,324,746 |

Stations discovered in the NCR box: 112.

## By pollutant

| pollutant | stations | usable hours | active hours | coverage |
|---|---:|---:|---:|---:|
| pm25 | 82 | 2,339,719 | 604,054 | 387.3% |
| pm10 | 81 | 2,285,600 | 595,268 | 384.0% |
| no2 | 81 | 2,141,441 | 595,262 | 359.7% |
| so2 | 72 | 1,878,942 | 516,697 | 363.6% |
| co | 81 | 1,601,358 | 592,637 | 270.2% |
| o3 | 81 | 2,139,574 | 593,320 | 360.6% |

## By region (nearest NCR city centre within 30 km, else Other NCR)

| region | pm25 | pm10 | no2 | so2 | co | o3 |
|---|---:|---:|---:|---:|---:|---:|
| Delhi | 42 st / 397.9% | 41 st / 398.7% | 41 st / 359.3% | 36 st / 371.3% | 41 st / 271.4% | 41 st / 361.3% |
| Faridabad | 7 st / 357.0% | 7 st / 352.8% | 7 st / 351.2% | 7 st / 349.7% | 7 st / 279.7% | 7 st / 354.0% |
| Ghaziabad | 4 st / 323.3% | 4 st / 318.3% | 4 st / 299.7% | 4 st / 294.5% | 4 st / 188.9% | 4 st / 298.1% |
| Gurugram | 12 st / 346.5% | 12 st / 325.2% | 12 st / 336.9% | 9 st / 325.8% | 12 st / 256.4% | 12 st / 337.8% |
| Noida | 6 st / 397.0% | 6 st / 397.4% | 6 st / 363.7% | 5 st / 366.2% | 6 st / 263.2% | 6 st / 360.8% |
| Other NCR | 11 st / 452.8% | 11 st / 457.1% | 11 st / 436.0% | 11 st / 431.2% | 11 st / 330.2% | 11 st / 434.1% |

## By month (all stations; usable / active)

| month | pm25 | pm10 | no2 | so2 | co | o3 |
|---|---:|---:|---:|---:|---:|---:|
| 2025-10 | 88.0% | 88.0% | 87.9% | 86.9% | 0.0% | 88.2% |
| 2025-11 | 89.8% | 90.3% | 90.3% | 89.8% | 0.0% | 90.2% |
| 2025-12 | 93.2% | 93.2% | 92.9% | 92.6% | 0.0% | 93.2% |
| 2026-01 | 64.0% | 63.7% | 63.3% | 63.2% | 0.0% | 63.0% |
| 2026-02 | 80.8% | 80.7% | 80.4% | 79.8% | 0.0% | 80.4% |
| 2026-03 | 90.0% | 89.2% | 89.9% | 89.8% | 0.0% | 89.7% |
| 2026-04 | 90.0% | 89.1% | 89.5% | 89.7% | 0.0% | 89.4% |
| 2026-05 | 87.0% | 86.4% | 86.7% | 86.0% | 0.0% | 86.5% |
| 2026-06 | 84.0% | 83.7% | 84.0% | 83.6% | 0.0% | 84.0% |
| 2026-07 | 90.3% | 91.2% | 92.2% | 91.2% | 0.0% | 92.5% |
| 2026-08 | 82.0% | 82.9% | 84.1% | 83.2% | 0.0% | 83.8% |
| 2026-09 | 90.6% | 91.8% | 92.9% | 92.2% | 0.0% | 92.5% |
| 2026-10 | 81.8% | 83.3% | 82.8% | 81.1% | 0.0% | 83.2% |

### Region x month, PM2.5

| region | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 | 2026-09 | 2026-10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Delhi | 92.0% | 93.0% | 95.5% | 65.4% | 83.3% | 92.9% | 91.8% | 90.0% | 85.9% | 91.5% | 83.2% | 91.0% | 83.0% |
| Gurugram | 83.7% | 87.5% | 92.3% | 63.1% | 79.0% | 83.0% | 87.3% | 84.9% | 82.1% | 88.7% | 82.4% | 91.8% | 82.8% |
| Other NCR | 90.4% | 88.4% | 93.1% | 63.4% | 77.6% | 89.9% | 90.8% | 83.1% | 84.1% | 86.6% | 78.8% | 87.5% | 85.8% |
| Noida | 90.6% | 91.5% | 92.9% | 65.1% | 82.6% | 91.3% | 91.3% | 89.0% | 85.4% | 87.2% | 83.2% | 92.1% | 84.2% |
| Ghaziabad | 91.7% | 87.3% | 91.4% | 64.2% | 81.7% | 90.9% | 91.6% | 85.3% | 80.1% | 91.7% | 75.4% | 90.7% | 81.8% |
| Faridabad | 64.7% | 76.6% | 83.5% | 56.9% | 70.7% | 84.0% | 81.6% | 77.3% | 77.6% | 92.3% | 81.3% | 88.4% | 64.4% |

## By station (PM2.5; all pollutants are in the JSON report)

| station | zone | agency | usable h | active h | coverage | gaps | longest gap h | first usable | last usable |
|---|---|---|---:|---:|---:|---:|---:|---|---|
| R K Puram, Delhi - DPCC (17) | Delhi | Delhi (DPCC) | 7,658 | 8,727 | 87.8% | 242 | 242 | 2025-10-09T00:00:00Z | 2026-10-07T14:00:00Z |
| Punjabi Bagh, Delhi - DPCC (50) | Delhi | Delhi (DPCC) | 7,601 | 8,727 | 87.1% | 265 | 242 | 2025-10-09T00:00:00Z | 2026-10-07T14:00:00Z |
| Anand Vihar, New Delhi - DPCC (235) | Delhi | Delhi (DPCC) | 7,560 | 8,727 | 86.6% | 255 | 242 | 2025-10-09T00:00:00Z | 2026-10-07T14:00:00Z |
| Mandir Marg, Delhi - DPCC (236) | Delhi | Other/unknown | 27,221 | 0 | n/a | 840 | 2160 | 2021-12-31T19:00:00Z | 2025-09-01T18:00:00Z |
| Vikas Sadan, Gurugram - HSPCB (301) | Gurugram | Haryana (HSPCB) | 28,764 | 8,727 | 329.6% | 706 | 6749 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| IHBAS, Delhi - CPCB (431) | Delhi | Other/unknown | 27,532 | 0 | n/a | 687 | 2160 | 2021-12-31T19:00:00Z | 2025-09-01T17:00:00Z |
| Pusa, Delhi - IMD (5404) | Delhi | IMD | 7,445 | 8,727 | 85.3% | 191 | 242 | 2025-10-09T00:00:00Z | 2026-10-07T14:00:00Z |
| Burari Crossing, New Delhi - IMD (5541) | Delhi | IMD | 33,408 | 8,727 | 382.8% | 356 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Aya Nagar, New Delhi - IMD (5570) | Gurugram | IMD | 7,459 | 8,727 | 85.5% | 163 | 456 | 2025-10-09T00:00:00Z | 2026-10-07T14:00:00Z |
| Sirifort, Delhi - CPCB (5586) | Delhi | CPCB | 33,750 | 8,727 | 386.7% | 594 | 2320 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| RIICO Ind. Area III, Bhiwadi - RSPCB (5588) | Other NCR | Rajasthan (RSPCB) | 32,538 | 8,727 | 372.8% | 647 | 6757 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Sector - 125, Noida, UP - UPPCB (5598) | Noida | Uttar Pradesh (UPPCB) | 34,760 | 8,727 | 398.3% | 660 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| North Campus, DU, Delhi - IMD (5610) | Delhi | IMD | 36,460 | 8,727 | 417.8% | 428 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| ITO, New Delhi - CPCB (5613) | Delhi | CPCB | 7,823 | 8,727 | 89.6% | 172 | 242 | 2025-10-09T00:00:00Z | 2026-10-07T14:00:00Z |
| Sector - 62, Noida, UP - IMD (5616) | Noida | IMD | 35,451 | 8,727 | 406.2% | 349 | 2160 | 2022-01-02T19:00:00Z | 2026-10-07T14:00:00Z |
| NSIT Dwarka, Delhi - CPCB (5622) | Gurugram | CPCB | 35,978 | 8,727 | 412.3% | 801 | 2165 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| DTU, New Delhi - CPCB (5626) | Delhi | CPCB | 34,697 | 8,727 | 397.6% | 919 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| CRRI Mathura Road, New Delhi - IMD (5627) | Delhi | IMD | 35,134 | 8,727 | 402.6% | 304 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Shadipur, Delhi - CPCB (5630) | Delhi | CPCB | 36,377 | 8,727 | 416.8% | 835 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Lodhi Road, New Delhi - IMD (5634) | Delhi | IMD | 37,296 | 8,727 | 427.4% | 323 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| IGI Airport (T3), Delhi - IMD (5650) | Delhi | IMD | 36,135 | 8,727 | 414.1% | 254 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Vasundhara, Ghaziabad - UPPCB (5665) | Ghaziabad | Uttar Pradesh (UPPCB) | 7,199 | 8,727 | 82.5% | 247 | 242 | 2025-10-09T03:00:00Z | 2026-10-07T14:00:00Z |
| Pusa, Delhi - DPCC (6356) | Delhi | Delhi (DPCC) | 37,535 | 8,727 | 430.1% | 201 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Punjabi Bagh, Delhi - DPCC (6357) | Delhi | Other/unknown | 28,627 | 0 | n/a | 396 | 2160 | 2021-12-31T19:00:00Z | 2025-09-01T11:00:00Z |
| Mandir Marg, New Delhi - DPCC (6358) | Delhi | Delhi (DPCC) | 7,306 | 8,727 | 83.7% | 362 | 242 | 2025-10-09T00:00:00Z | 2026-10-07T14:00:00Z |
| IHBAS, Dilshad Garden,New Delhi - CPCB (6359) | Delhi | CPCB | 7,755 | 8,727 | 88.9% | 245 | 242 | 2025-10-09T00:00:00Z | 2026-10-07T14:00:00Z |
| Indirapuram, Ghaziabad - UPPCB (6924) | Ghaziabad | Uttar Pradesh (UPPCB) | 36,843 | 8,727 | 422.2% | 417 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Major Dhyan Chand National Stadium, Delhi - DPCC (6929) | Delhi | Delhi (DPCC) | 36,565 | 8,727 | 419.0% | 538 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Dwarka-Sector 8, Delhi - DPCC (6931) | Gurugram | Delhi (DPCC) | 37,213 | 8,727 | 426.4% | 327 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Alipur, Delhi - DPCC (6932) | Delhi | Delhi (DPCC) | 36,318 | 8,727 | 416.2% | 482 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Dr. Karni Singh Shooting Range, Delhi - DPCC (6934) | Faridabad | Delhi (DPCC) | 36,900 | 8,727 | 422.8% | 416 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Arya Nagar, Bahadurgarh - HSPCB (6936) | Gurugram | Haryana (HSPCB) | 31,633 | 8,727 | 362.5% | 726 | 6869 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Vivek Vihar, Delhi - DPCC (6938) | Delhi | Delhi (DPCC) | 36,366 | 8,727 | 416.7% | 341 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Municipal Corporation Office, Dharuhera -  HSPCB (6949) | Other NCR | Haryana (HSPCB) | 29,228 | 8,727 | 334.9% | 1242 | 7000 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Murthal, Sonipat - HSPCB (6951) | Other NCR | Haryana (HSPCB) | 6,991 | 8,727 | 80.1% | 192 | 281 | 2025-10-09T00:00:00Z | 2026-10-07T14:00:00Z |
| Sector-2 IMT, Manesar - HSPCB (6953) | Gurugram | Haryana (HSPCB) | 31,489 | 8,727 | 360.8% | 687 | 6785 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Jawaharlal Nehru Stadium, Delhi - DPCC (6957) | Delhi | Delhi (DPCC) | 36,446 | 8,727 | 417.6% | 382 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Patparganj, Delhi - DPCC (6960) | Delhi | Delhi (DPCC) | 36,514 | 8,727 | 418.4% | 342 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Nathu Colony, Ballabgarh - HSPCB (6972) | Faridabad | Haryana (HSPCB) | 32,013 | 8,727 | 366.8% | 811 | 7049 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Jai Bhim Nagar, Meerut - UPPCB (6976) | Other NCR | Uttar Pradesh (UPPCB) | 34,733 | 8,727 | 398.0% | 668 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Knowledge Park - III, Greater Noida - UPPCB (6978) | Noida | Uttar Pradesh (UPPCB) | 31,646 | 8,727 | 362.6% | 528 | 6749 | 2022-01-01T02:00:00Z | 2026-10-07T14:00:00Z |
| Sector-1, Noida - UPPCB (6980) | Noida | Uttar Pradesh (UPPCB) | 36,018 | 8,727 | 412.7% | 464 | 2167 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Knowledge Park - V, Greater Noida - UPPCB (6986) | Noida | Uttar Pradesh (UPPCB) | 33,521 | 8,727 | 384.1% | 372 | 6749 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Sector-116, Noida - UPPCB (6988) | Noida | Uttar Pradesh (UPPCB) | 36,500 | 8,727 | 418.2% | 449 | 2163 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Loni, Ghaziabad - UPPCB (7005) | Delhi | Uttar Pradesh (UPPCB) | 33,737 | 8,727 | 386.6% | 803 | 2167 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| R K Puram, Delhi - DPCC (7044) | Delhi | Other/unknown | 28,682 | 0 | n/a | 390 | 2160 | 2021-12-31T19:00:00Z | 2025-09-01T12:00:00Z |
| Shyam Nagar, Palwal - HSPCB (7280) | Faridabad | Haryana (HSPCB) | 7,240 | 8,727 | 83.0% | 328 | 242 | 2025-10-09T00:00:00Z | 2026-10-07T14:00:00Z |
| Shyam Nagar, Palwal - HSPCB (7281) | Faridabad | Other/unknown | 23,934 | 0 | n/a | 573 | 99 | 2021-12-31T19:00:00Z | 2024-12-18T14:00:00Z |
| Ganga Nagar, Meerut - UPPCB (7833) | Other NCR | Uttar Pradesh (UPPCB) | 33,454 | 8,727 | 383.3% | 486 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| New Delhi (8118) | Delhi | Other/unknown | 39,397 | 8,781 | 448.7% | 138 | 869 | 2021-12-31T19:00:00Z | 2026-10-09T20:00:00Z |
| Jahangirpuri, Delhi - DPCC (8235) | Delhi | Delhi (DPCC) | 36,308 | 8,711 | 416.8% | 555 | 2167 | 2021-12-31T19:00:00Z | 2026-10-06T22:00:00Z |
| Okhla Phase-2, Delhi - DPCC (8239) | Delhi | Delhi (DPCC) | 37,176 | 8,727 | 426.0% | 299 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Anand Vihar, Hapur - UPPCB (8319) | Ghaziabad | Uttar Pradesh (UPPCB) | 32,036 | 8,726 | 367.1% | 450 | 6756 | 2021-12-31T19:00:00Z | 2026-10-07T13:00:00Z |
| Nehru Nagar, Delhi - DPCC (8365) | Delhi | Delhi (DPCC) | 36,861 | 8,727 | 422.4% | 391 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Bawana, Delhi - DPCC (8472) | Delhi | Delhi (DPCC) | 36,714 | 8,727 | 420.7% | 467 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Sonia Vihar, Delhi - DPCC (8475) | Delhi | Delhi (DPCC) | 36,449 | 8,727 | 417.7% | 418 | 2160 | 2022-01-01T01:00:00Z | 2026-10-07T14:00:00Z |
| Wazirpur, Delhi - DPCC (8915) | Delhi | Delhi (DPCC) | 36,748 | 8,727 | 421.1% | 390 | 2160 | 2022-01-01T06:00:00Z | 2026-10-07T14:00:00Z |
| Ashok Vihar, Delhi - DPCC (8917) | Delhi | Delhi (DPCC) | 36,228 | 8,727 | 415.1% | 421 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Sri Aurobindo Marg, Delhi - DPCC (10484) | Delhi | Delhi (DPCC) | 36,203 | 8,727 | 414.8% | 355 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Narela, Delhi - DPCC (10485) | Delhi | Delhi (DPCC) | 37,193 | 8,727 | 426.2% | 283 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Mundka, Delhi - DPCC (10486) | Delhi | Delhi (DPCC) | 36,726 | 8,727 | 420.8% | 422 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Anand Vihar, Delhi - DPCC (10487) | Delhi | Other/unknown | 27,351 | 0 | n/a | 522 | 2160 | 2021-12-31T19:00:00Z | 2025-09-01T18:00:00Z |
| Najafgarh, Delhi - DPCC (10488) | Gurugram | Delhi (DPCC) | 35,650 | 8,727 | 408.5% | 663 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| ITO, Delhi - CPCB (10489) | Delhi | Other/unknown | 28,234 | 0 | n/a | 238 | 2160 | 2021-12-31T19:00:00Z | 2025-09-01T18:00:00Z |
| Sector 30, Faridabad - HSPCB (10820) | Faridabad | Haryana (HSPCB) | 24,478 | 8,727 | 280.5% | 1503 | 6778 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Sector-51, Gurugram - HSPCB (10825) | Gurugram | Haryana (HSPCB) | 32,280 | 8,727 | 369.9% | 739 | 6756 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Rohini, Delhi - DPCC (10831) | Delhi | Delhi (DPCC) | 37,234 | 8,727 | 426.7% | 296 | 2160 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Teri Gram, Gurugram - HSPCB (10900) | Gurugram | Haryana (HSPCB) | 30,552 | 8,724 | 350.2% | 983 | 6756 | 2021-12-31T19:00:00Z | 2026-10-07T11:00:00Z |
| Murthal, Sonipat - HSPCB (10906) | Other NCR | Other/unknown | 19,079 | 0 | n/a | 652 | 865 | 2021-12-31T19:00:00Z | 2024-12-18T16:00:00Z |
| Sector 11, Faridabad - HSPCB (10908) | Faridabad | Haryana (HSPCB) | 32,146 | 8,681 | 370.3% | 531 | 6757 | 2021-12-31T19:00:00Z | 2026-10-05T16:00:00Z |
| Sanjay Nagar, Ghaziabad - UPPCB (10919) | Ghaziabad | Uttar Pradesh (UPPCB) | 36,764 | 8,727 | 421.3% | 526 | 2160 | 2021-12-31T20:00:00Z | 2026-10-07T14:00:00Z |
| New Industrial Town, Faridabad - HSPCB (10920) | Faridabad | Haryana (HSPCB) | 30,039 | 8,727 | 344.2% | 1006 | 4553 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| NISE Gwal Pahari, Gurugram - IMD (10921) | Gurugram | IMD | 26,208 | 8,727 | 300.3% | 712 | 6749 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Chandni Chowk, Delhi - IITM (11603) | Delhi | Other/unknown | 20,446 | 8,727 | 234.3% | 1101 | 6518 | 2021-12-31T19:00:00Z | 2026-10-07T14:00:00Z |
| Lodhi Road, Delhi - IITM (11607) | Delhi | Other/unknown | 1,755 | 1,903 | 92.2% | 48 | 20 | 2025-10-09T00:00:00Z | 2025-12-27T06:00:00Z |
| Sardar Patel Inter College, Baghpat - UPPCB (301388) | Other NCR | Uttar Pradesh (UPPCB) | 28,981 | 8,727 | 332.1% | 973 | 6762 | 2022-01-13T12:00:00Z | 2026-10-07T14:00:00Z |
| Vasundhara Nagar_UIT, Bhiwadi - RSPCB (3409519) | Other NCR | Rajasthan (RSPCB) | 14,458 | 8,727 | 165.7% | 309 | 6749 | 2024-02-26T10:00:00Z | 2026-10-07T14:00:00Z |
| Amity University, Panchgaon - IITM (3410004) | Gurugram | Other/unknown | 7,419 | 8,727 | 85.0% | 177 | 242 | 2025-10-09T00:00:00Z | 2026-10-07T14:00:00Z |
| Aya Nagar, Delhi - IMD (9000000108) | Gurugram | Delhi (DPCC) | 27,978 | 0 | n/a | 374 | 2160 | 2021-12-31T19:00:00Z | 2025-09-01T18:00:00Z |
| Yamunapuram, Bulandshahr - UPPCB (9000001542) | Other NCR | Uttar Pradesh (UPPCB) | 25,485 | 0 | n/a | 209 | 196 | 2021-12-31T19:00:00Z | 2024-12-31T18:00:00Z |
| Pallavpuram Phase 2, Meerut - UPPCB (9000005257) | Other NCR | Uttar Pradesh (UPPCB) | 28,437 | 0 | n/a | 258 | 2167 | 2021-12-31T19:00:00Z | 2025-09-01T18:00:00Z |
| Kalindi Kunj, Khurja - UPPCB (9000005603) | Other NCR | Uttar Pradesh (UPPCB) | 23,253 | 0 | n/a | 813 | 2160 | 2022-06-02T10:00:00Z | 2025-09-01T18:00:00Z |

## Quality flags (hours carrying each flag)

| pollutant | flags |
|---|---|
| pm25 | FLATLINE: 6,453, LOW_COVERAGE: 66,216, MULTI_SENSOR: 8,814, NEGATIVE: 16, NULL_VALUE: 479, OUT_OF_RANGE: 2, SENSOR_CONFLICT: 47,515 |
| pm10 | FLATLINE: 6,079, LOW_COVERAGE: 63,507, MULTI_SENSOR: 6,589, NEGATIVE: 4, NULL_VALUE: 811, SENSOR_CONFLICT: 33,033 |
| no2 | FLATLINE: 3,627, LOW_COVERAGE: 65,478, MULTI_SENSOR: 2,947, NEGATIVE: 47, NULL_VALUE: 288, SENSOR_CONFLICT: 48,560, UNIT_CONVERTED: 513,298 |
| so2 | FLATLINE: 4,654, LOW_COVERAGE: 63,481, MULTI_SENSOR: 913, NEGATIVE: 36, NULL_VALUE: 91, OUT_OF_RANGE: 8, SENSOR_CONFLICT: 16,828, UNIT_CONVERTED: 442,871 |
| co | FLATLINE: 26,303, LOW_COVERAGE: 69,536, MULTI_SENSOR: 3,687, NEGATIVE: 47, NULL_VALUE: 445, SENSOR_CONFLICT: 37,723, UNIT_CONVERTED: 2,111,413, UNIT_SUSPECT: 510,500 |
| o3 | FLATLINE: 6,014, LOW_COVERAGE: 65,669, MULTI_SENSOR: 4,898, NEGATIVE: 16, NULL_VALUE: 201, SENSOR_CONFLICT: 42,249 |

Hard flags (value unusable): NULL_VALUE, NEGATIVE, OUT_OF_RANGE, UNIT_UNKNOWN, UNIT_SUSPECT, PERIOD_IRREGULAR. Soft flags (value kept): LOW_COVERAGE, FLATLINE, UNIT_CONVERTED, REVISED, SENSOR_CONFLICT, MULTI_SENSOR, ALIGN_ROUNDED.

## Units as received and as standardised

| pollutant | original unit | standard unit | hours |
|---|---|---|---:|
| co | mg/m³ | µg/m³ | 1,601,358 |
| co | ppb | none | 445 |
| co | ppb | µg/m³ | 510,055 |
| no2 | ppb | none | 288 |
| no2 | ppb | µg/m³ | 513,298 |
| no2 | µg/m³ | µg/m³ | 1,628,190 |
| o3 | µg/m³ | none | 201 |
| o3 | µg/m³ | µg/m³ | 2,139,590 |
| pm10 | µg/m³ | none | 811 |
| pm10 | µg/m³ | µg/m³ | 2,285,604 |
| pm25 | µg/m³ | none | 479 |
| pm25 | µg/m³ | µg/m³ | 2,339,737 |
| so2 | ppb | none | 91 |
| so2 | ppb | µg/m³ | 442,871 |
| so2 | µg/m³ | µg/m³ | 1,436,115 |

## Sensors whose labelled unit contradicts their magnitude (excluded, not rescaled)

After conversion to µg/m³ their median either differs by more than 20x from the median of sensors that report this pollutant natively in µg/m³, or (CO) is below the physical-plausibility floor, so the unit label cannot be right. Their values stay in the raw table unchanged; the rows are flagged UNIT_SUSPECT and are not used.

| pollutant | labelled unit | sensors |
|---|---|---:|
| co | ppb | 68 |

| sensor | station | pollutant | unit | median after conversion (µg/m³) | reference median (µg/m³) | ratio |
|---:|---|---|---|---:|---:|---:|
| 12234782 | R K Puram, Delhi - DPCC (17) | co | ppb | 1.27 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234791 | Punjabi Bagh, Delhi - DPCC (50) | co | ppb | 1.11 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235605 | Anand Vihar, New Delhi - DPCC (235) | co | ppb | 1.84 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 14258983 | Vikas Sadan, Gurugram - HSPCB (301) | co | ppb | 2.06 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234697 | Pusa, Delhi - IMD (5404) | co | ppb | 1.12 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234679 | Burari Crossing, New Delhi - IMD (5541) | co | ppb | 1.09 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234703 | Aya Nagar, New Delhi - IMD (5570) | co | ppb | 0.974 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234764 | Sirifort, Delhi - CPCB (5586) | co | ppb | 0.719 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234827 | RIICO Ind. Area III, Bhiwadi - RSPCB (5588) | co | ppb | 0.911 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235182 | Sector - 125, Noida, UP - UPPCB (5598) | co | ppb | 0.985 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234685 | North Campus, DU, Delhi - IMD (5610) | co | ppb | 1.35 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234748 | ITO, New Delhi - CPCB (5613) | co | ppb | 1.18 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234715 | Sector - 62, Noida, UP - IMD (5616) | co | ppb | 0.647 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234739 | NSIT Dwarka, Delhi - CPCB (5622) | co | ppb | 1.17 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234755 | DTU, New Delhi - CPCB (5626) | co | ppb | 0.664 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234673 | CRRI Mathura Road, New Delhi - IMD (5627) | co | ppb | 1.21 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234721 | Shadipur, Delhi - CPCB (5630) | co | ppb | 1.14 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234709 | Lodhi Road, New Delhi - IMD (5634) | co | ppb | 0.765 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234691 | IGI Airport (T3), Delhi - IMD (5650) | co | ppb | 0.949 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235155 | Vasundhara, Ghaziabad - UPPCB (5665) | co | ppb | 1.11 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235316 | Pusa, Delhi - DPCC (6356) | co | ppb | 1.67 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234773 | Mandir Marg, New Delhi - DPCC (6358) | co | ppb | 1.43 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234730 | IHBAS, Dilshad Garden,New Delhi - CPCB (6359) | co | ppb | 1.32 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235774 | Indirapuram, Ghaziabad - UPPCB (6924) | co | ppb | 1.08 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235042 | Major Dhyan Chand National Stadium, Delhi - DPCC (6929) | co | ppb | 1.19 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235015 | Dwarka-Sector 8, Delhi - DPCC (6931) | co | ppb | 1.07 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235693 | Alipur, Delhi - DPCC (6932) | co | ppb | 0.922 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235006 | Dr. Karni Singh Shooting Range, Delhi - DPCC (6934) | co | ppb | 0.888 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 14233899 | Arya Nagar, Bahadurgarh - HSPCB (6936) | co | ppb | 1.07 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235128 | Vivek Vihar, Delhi - DPCC (6938) | co | ppb | 1.42 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 14291086 | Municipal Corporation Office, Dharuhera -  HSPCB (6949) | co | ppb | 1.33 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 14258138 | Murthal, Sonipat - HSPCB (6951) | co | ppb | 0.765 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 14250040 | Sector-2 IMT, Manesar - HSPCB (6953) | co | ppb | 0.479 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235033 | Jawaharlal Nehru Stadium, Delhi - DPCC (6957) | co | ppb | 1.39 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235096 | Patparganj, Delhi - DPCC (6960) | co | ppb | 1.24 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 14283595 | Nathu Colony, Ballabgarh - HSPCB (6972) | co | ppb | 1.01 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235864 | Jai Bhim Nagar, Meerut - UPPCB (6976) | co | ppb | 1 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235191 | Knowledge Park - III, Greater Noida - UPPCB (6978) | co | ppb | 0.911 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235946 | Sector-1, Noida - UPPCB (6980) | co | ppb | 1.13 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235930 | Knowledge Park - V, Greater Noida - UPPCB (6986) | co | ppb | 0.739 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235939 | Sector-116, Noida - UPPCB (6988) | co | ppb | 1.02 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235783 | Loni, Ghaziabad - UPPCB (7005) | co | ppb | 1.25 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 14249199 | Shyam Nagar, Palwal - HSPCB (7280) | co | ppb | 0.782 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12236079 | Ganga Nagar, Meerut - UPPCB (7833) | co | ppb | 1.08 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235024 | Jahangirpuri, Delhi - DPCC (8235) | co | ppb | 1.39 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235069 | Okhla Phase-2, Delhi - DPCC (8239) | co | ppb | 1.31 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235684 | Anand Vihar, Hapur - UPPCB (8319) | co | ppb | 1.06 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235078 | Nehru Nagar, Delhi - DPCC (8365) | co | ppb | 1.26 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235289 | Bawana, Delhi - DPCC (8472) | co | ppb | 1.16 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235105 | Sonia Vihar, Delhi - DPCC (8475) | co | ppb | 1.65 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235119 | Wazirpur, Delhi - DPCC (8915) | co | ppb | 1.39 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12234997 | Ashok Vihar, Delhi - DPCC (8917) | co | ppb | 1.13 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235307 | Sri Aurobindo Marg, Delhi - DPCC (10484) | co | ppb | 0.966 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235051 | Narela, Delhi - DPCC (10485) | co | ppb | 1.04 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235298 | Mundka, Delhi - DPCC (10486) | co | ppb | 1.18 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235060 | Najafgarh, Delhi - DPCC (10488) | co | ppb | 0.842 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12236231 | Sector 30, Faridabad - HSPCB (10820) | co | ppb | 1.37 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12236254 | Sector-51, Gurugram - HSPCB (10825) | co | ppb | 0.605 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235087 | Rohini, Delhi - DPCC (10831) | co | ppb | 0.951 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 14516015 | Teri Gram, Gurugram - HSPCB (10900) | co | ppb | 0.685 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12236240 | Sector 11, Faridabad - HSPCB (10908) | co | ppb | 1.19 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235765 | Sanjay Nagar, Ghaziabad - UPPCB (10919) | co | ppb | 0.868 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12236222 | New Industrial Town, Faridabad - HSPCB (10920) | co | ppb | 0.292 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12235702 | NISE Gwal Pahari, Gurugram - IMD (10921) | co | ppb | 1.04 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12236356 | Chandni Chowk, Delhi - IITM (11603) | co | ppb | 2.02 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12237030 | Sardar Patel Inter College, Baghpat - UPPCB (301388) | co | ppb | 0.67 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12238635 | Vasundhara Nagar_UIT, Bhiwadi - RSPCB (3409519) | co | ppb | 0.805 | none (physical-plausibility floor) | none (physical-plausibility floor) |
| 12238720 | Amity University, Panchgaon - IITM (3410004) | co | ppb | 0.899 | none (physical-plausibility floor) | none (physical-plausibility floor) |

## Duplicates

Raw rows 13,152,889 reduced to 12,899,133 clean hourly rows; 253,756 hours had more than one sensor reporting.

## Weather (Open-Meteo archive, model/reanalysis values)

82 station points served by 37 distinct provider grid cells (stations in one cell share identical weather), 3,324,746 hourly rows, 11,830 flagged provisional (fetched within 7 days of the value's time).

| variable | null rate |
|---|---:|
| temperature_2m | 0.0% |
| relative_humidity_2m | 0.0% |
| dew_point_2m | 0.0% |
| surface_pressure | 0.0% |
| wind_speed_10m | 0.0% |
| wind_direction_10m | 0.0% |
| wind_gusts_10m | 0.0% |
| precipitation | 0.0% |
| cloud_cover | 0.0% |
| boundary_layer_height | 10.8% |
| shortwave_radiation | 0.0% |

| month | weather coverage of the window |
|---|---:|
| 2025-10 | 121.6% |
| 2025-11 | 85.4% |
| 2025-12 | 85.4% |
| 2026-01 | 85.4% |
| 2026-02 | 85.4% |
| 2026-03 | 85.4% |
| 2026-04 | 85.4% |
| 2026-05 | 85.4% |
| 2026-06 | 85.4% |
| 2026-07 | 85.4% |
| 2026-08 | 85.4% |
| 2026-09 | 85.4% |
| 2026-10 | 85.0% |

## Publication latency

Age of each station's newest hourly value at the moment it was fetched: minimum 9.0 h, median 62.4 h, maximum 15854.5 h over 82 stations.

## Which forecasting targets and horizons the data can support

A station counts toward a (pollutant, horizon) cell if it has at least 1,500 origin/target pairs with weather present and a span of at least 120 days. Verdict: **supported** if at least 20 stations qualify, **limited** if at least 5, else **insufficient**. These thresholds are this pipeline's own conservative choices for judging whether a station-level model could be trained and tested; they are not a statistical guarantee.

| pollutant | +1 h | +3 h | +6 h | +12 h | +24 h | +48 h | +72 h |
|---|---|---|---|---|---|---|---|
| pm25 | supported (81 st) | supported (81 st) | supported (81 st) | supported (81 st) | supported (81 st) | supported (81 st) | supported (81 st) |
| pm10 | supported (80 st) | supported (80 st) | supported (80 st) | supported (80 st) | supported (80 st) | supported (80 st) | supported (80 st) |
| no2 | supported (80 st) | supported (80 st) | supported (80 st) | supported (80 st) | supported (80 st) | supported (80 st) | supported (80 st) |
| so2 | supported (71 st) | supported (71 st) | supported (71 st) | supported (71 st) | supported (71 st) | supported (71 st) | supported (71 st) |
| co | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) |
| o3 | supported (80 st) | supported (80 st) | supported (80 st) | supported (80 st) | supported (80 st) | supported (80 st) | supported (80 st) |

Operational caveat: the figures above say whether a model can be *trained and evaluated*. Using it live additionally requires the feed's publication latency (section above) to be smaller than the forecast horizon.

## Ingest runs

| run | kind | started | status | requests | rows | note |
|---|---|---|---|---:|---:|---|
| 11b072ca9b72 | discover | 2026-10-09T20:59:39Z | ok | 0 | 0 | {"stations": 108, "stations_in_window": 70, "sensors": 742} |
| 82c62a280eaf | ingest-air | 2026-10-09T21:01:13Z | ok | 12 | 9517 | stopped at the request budget (12); run again to resume |
| 1838b9afb42c | ingest-air | 2026-10-09T21:01:48Z | running | 0 | 0 |  |
| 54185c8bf00a | ingest-weather | 2026-10-09T21:01:51Z | ok | 70 | 614740 |  |
| 5267efdfa5c2 | ingest-air | 2026-10-09T21:08:31Z | partial | 985 | 747536 | stopped after 5 consecutive failures (possible rate limit); run again to resume |
| c5d9a7dd1778 | ingest-air | 2026-10-09T21:30:02Z | running | 0 | 0 |  |
| bcd0df20ba20 | ingest-air | 2026-10-09T21:48:36Z | ok | 2263 | 1561450 |  |
| 9155e0032457 | ingest-air | 2026-10-09T22:43:34Z | running | 0 | 0 |  |
| e08accc62043 | ingest-weather | 2026-10-09T22:46:41Z | ok | 28 | 70 |  |
| 6ab7d9194fdb | ingest-air-xkdr | 2026-10-10T04:35:52Z | ok | 1694 | 10161751 | failed_windows=0 |
| 3d22c083e6ed | ingest-weather | 2026-10-10T04:37:12Z | partial | 158 | 1507680 | stopped after 5 consecutive failures; run again to resume |
| 1507c9eda7ab | ingest-weather | 2026-10-10T04:49:13Z | partial | 5 | 0 | stopped after 5 consecutive failures; run again to resume |
| 1f8c679d050c | ingest-weather | 2026-10-10T05:09:56Z | ok | 127 | 1202256 |  |
