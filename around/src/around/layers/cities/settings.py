from __future__ import annotations

CITY_CAPITAL_ZOOM = 1.0
CITY_MAJOR_ZOOM = 2.0
FORECAST_DAYS_AHEAD = 3

CITY_CONFIG = {
    "enabled": True,
    "color": "#66ff99",
    # Marker/label color gradient driven by each city's current temperature
    # relative to the coldest and hottest cities we currently have a
    # reading for (see WeatherStationCache.temperature_range) -- not a
    # fixed threshold.
    "temperature_cold_color": "#508cff",
    "temperature_hot_color": "#ff4646",
}

# Open-Meteo needs no API key. Weather is fetched on demand for whichever
# city is currently selected, not pre-fetched for the whole list.
WEATHER_API_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_REFRESH_INTERVAL_SECONDS = 15 * 60
# A city whose last fetch attempt failed is retried much sooner than a
# healthy one, instead of waiting out the full refresh interval.
WEATHER_RETRY_INTERVAL_SECONDS = 15
# Readings are persisted here so a fetch failure (or an app restart) can
# fall back to the last known data instead of showing nothing.
WEATHER_CACHE_FILENAME = "cities_weather_cache.json"

# name, latitude, longitude, is_capital, country, population, area_km2
#
# Population and area are approximate reference figures meant to give a
# sense of scale, not a live/current statistic -- update as needed.
CITY_DATA = [
    ("Reykjavik", 64.1466, -21.9426, True, "Iceland", 135000, 274),
    ("London", 51.5074, -0.1278, True, "United Kingdom", 8982000, 1572),
    ("Paris", 48.8566, 2.3522, True, "France", 2148000, 105),
    ("Madrid", 40.4168, -3.7038, True, "Spain", 3223000, 604),
    ("Lisbon", 38.7223, -9.1393, True, "Portugal", 545000, 100),
    ("Dublin", 53.3498, -6.2603, True, "Ireland", 592000, 115),
    ("Oslo", 59.9139, 10.7522, True, "Norway", 700000, 454),
    ("Stockholm", 59.3293, 18.0686, True, "Sweden", 978000, 188),
    ("Helsinki", 60.1699, 24.9384, True, "Finland", 658000, 214),
    ("Copenhagen", 55.6761, 12.5683, True, "Denmark", 660000, 86),
    ("Berlin", 52.52, 13.405, True, "Germany", 3645000, 891),
    ("Amsterdam", 52.3676, 4.9041, True, "Netherlands", 872000, 219),
    ("Brussels", 50.8503, 4.3517, True, "Belgium", 185000, 33),
    ("Vienna", 48.2082, 16.3738, True, "Austria", 1920000, 415),
    ("Prague", 50.0755, 14.4378, True, "Czechia", 1309000, 496),
    ("Warsaw", 52.2297, 21.0122, True, "Poland", 1860000, 517),
    ("Budapest", 47.4979, 19.0402, True, "Hungary", 1706000, 525),
    ("Bucharest", 44.4268, 26.1025, True, "Romania", 1716000, 228),
    ("Athens", 37.9838, 23.7275, True, "Greece", 664000, 39),
    ("Rome", 41.9028, 12.4964, True, "Italy", 2873000, 1287),
    ("Bern", 46.948, 7.4474, True, "Switzerland", 134000, 51),
    ("Zagreb", 45.815, 15.9819, True, "Croatia", 806000, 641),
    ("Belgrade", 44.7866, 20.4489, True, "Serbia", 1166000, 359),
    ("Sofia", 42.6977, 23.3219, True, "Bulgaria", 1272000, 492),
    ("Kyiv", 50.4501, 30.5234, True, "Ukraine", 2952000, 839),
    ("Moscow", 55.7558, 37.6173, True, "Russia", 12655000, 2511),
    ("Ankara", 39.9334, 32.8597, True, "Turkey", 5747000, 2500),
    ("Tbilisi", 41.7151, 44.8271, True, "Georgia", 1154000, 720),
    ("Yerevan", 40.1872, 44.5152, True, "Armenia", 1075000, 223),
    ("Baku", 40.4093, 49.8671, True, "Azerbaijan", 2300000, 2140),
    ("Tehran", 35.6892, 51.389, True, "Iran", 9038000, 730),
    ("Baghdad", 33.3152, 44.3661, True, "Iraq", 7922000, 673),
    ("Riyadh", 24.7136, 46.6753, True, "Saudi Arabia", 7231000, 1973),
    ("Kuwait City", 29.3759, 47.9774, True, "Kuwait", 3115000, 200),
    ("Doha", 25.2854, 51.531, True, "Qatar", 1450000, 132),
    ("Abu Dhabi", 24.4539, 54.3773, True, "United Arab Emirates", 1807000, 972),
    ("Muscat", 23.588, 58.3829, True, "Oman", 1560000, 3500),
    ("Cairo", 30.0444, 31.2357, True, "Egypt", 10230000, 606),
    ("Tripoli", 32.8872, 13.1913, True, "Libya", 1126000, 400),
    ("Tunis", 36.8065, 10.1815, True, "Tunisia", 638000, 213),
    ("Algiers", 36.7538, 3.0588, True, "Algeria", 2364000, 273),
    ("Rabat", 34.0209, -6.8416, True, "Morocco", 577000, 117),
    ("Dakar", 14.7167, -17.4677, True, "Senegal", 1146000, 82),
    ("Accra", 5.6037, -0.187, True, "Ghana", 2388000, 225),
    ("Abuja", 9.0765, 7.3986, True, "Nigeria", 3278000, 1769),
    ("Nairobi", -1.2921, 36.8219, True, "Kenya", 4397000, 696),
    ("Addis Ababa", 9.032, 38.7469, True, "Ethiopia", 5228000, 527),
    ("Johannesburg", -26.2041, 28.0473, False, "South Africa", 5782000, 1645),
    ("Cape Town", -33.9249, 18.4241, False, "South Africa", 4710000, 2461),
    ("Pretoria", -25.7479, 28.2293, True, "South Africa", 741651, 6298),
    ("Washington", 38.9072, -77.0369, True, "United States", 690000, 177),
    ("Ottawa", 45.4215, -75.6972, True, "Canada", 1017000, 2790),
    ("Mexico City", 19.4326, -99.1332, True, "Mexico", 9209000, 1485),
    ("Havana", 23.1136, -82.3666, True, "Cuba", 2132000, 728),
    ("Panama City", 8.9824, -79.5199, True, "Panama", 880691, 275),
    ("Bogota", 4.711, -74.0721, True, "Colombia", 7743955, 1587),
    ("Quito", -0.1807, -78.4678, True, "Ecuador", 1978376, 4235),
    ("Lima", -12.0464, -77.0428, True, "Peru", 9674755, 2672),
    ("La Paz", -16.4897, -68.1193, True, "Bolivia", 816044, 472),
    ("Santiago", -33.4489, -70.6693, True, "Chile", 5220000, 641),
    ("Buenos Aires", -34.6037, -58.3816, True, "Argentina", 3120000, 203),
    ("Montevideo", -34.9011, -56.1645, True, "Uruguay", 1319108, 530),
    ("Brasilia", -15.7939, -47.8828, True, "Brazil", 3055149, 5802),
    ("Rio de Janeiro", -22.9068, -43.1729, False, "Brazil", 6747815, 1200),
    ("Sao Paulo", -23.5505, -46.6333, False, "Brazil", 12325232, 1521),
    ("Tokyo", 35.6762, 139.6503, True, "Japan", 13960000, 2194),
    ("Seoul", 37.5665, 126.978, True, "South Korea", 9411000, 605),
    ("Beijing", 39.9042, 116.4074, True, "China", 21540000, 16410),
    ("Shanghai", 31.2304, 121.4737, False, "China", 24870000, 6340),
    ("Hong Kong", 22.3193, 114.1694, False, "China", 7481800, 1106),
    ("Taipei", 25.033, 121.5654, True, "Taiwan", 2646000, 272),
    ("Manila", 14.5995, 120.9842, True, "Philippines", 1846513, 43),
    ("Bangkok", 13.7563, 100.5018, True, "Thailand", 10539000, 1569),
    ("Hanoi", 21.0278, 105.8342, True, "Vietnam", 8246600, 3359),
    ("Jakarta", -6.2088, 106.8456, True, "Indonesia", 10562088, 662),
    ("Kuala Lumpur", 3.139, 101.6869, True, "Malaysia", 1982112, 243),
    ("Singapore", 1.3521, 103.8198, True, "Singapore", 5921231, 729),
    ("New Delhi", 28.6139, 77.209, True, "India", 249998, 43),
    ("Mumbai", 19.076, 72.8777, False, "India", 12442373, 603),
    ("Dhaka", 23.8103, 90.4125, True, "Bangladesh", 8906039, 306),
    ("Islamabad", 33.6844, 73.0479, True, "Pakistan", 1014825, 906),
    ("Kathmandu", 27.7172, 85.324, True, "Nepal", 975453, 50),
    ("Colombo", 6.9271, 79.8612, True, "Sri Lanka", 752993, 37),
    ("Canberra", -35.2809, 149.13, True, "Australia", 462213, 814),
    ("Sydney", -33.8688, 151.2093, False, "Australia", 5367206, 12368),
    ("Melbourne", -37.8136, 144.9631, False, "Australia", 5078193, 9993),
    ("Wellington", -41.2866, 174.7756, True, "New Zealand", 212700, 289),
    ("Auckland", -36.8509, 174.7645, False, "New Zealand", 1657200, 4942),
    ("Honolulu", 21.3069, -157.8583, False, "United States", 350964, 177),
    ("Anchorage", 61.2181, -149.9003, False, "United States", 291247, 4412),
    ("Los Angeles", 34.0522, -118.2437, False, "United States", 3898747, 1302),
    ("San Francisco", 37.7749, -122.4194, False, "United States", 873965, 121),
    ("New York", 40.7128, -74.006, False, "United States", 8336817, 784),
    ("Toronto", 43.6532, -79.3832, False, "Canada", 2794356, 630),
    ("Vancouver", 49.2827, -123.1207, False, "Canada", 662248, 115),
    ("Istanbul", 41.0082, 28.9784, False, "Turkey", 15462452, 5461),
    ("Dubai", 25.2048, 55.2708, False, "United Arab Emirates", 3478300, 4114),
    ("Milan", 45.4642, 9.19, False, "Italy", 1371498, 182),
    ("Barcelona", 41.3874, 2.1686, False, "Spain", 1620343, 101),
    ("Munich", 48.1351, 11.582, False, "Germany", 1512491, 311),
    ("Frankfurt", 50.1109, 8.6821, False, "Germany", 773068, 248),
    ("Zurich", 47.3769, 8.5417, False, "Switzerland", 421878, 88),
]
