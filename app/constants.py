"""Scientific and technical constants used by the calculation engine.

These values are not business parameters and should not be edited from the
administration interface.
"""

from math import pi, sqrt


GRAVITY = 9.81
WATER_DENSITY = 1000.0

WATTS_PER_KILOWATT = 1000.0
LITERS_PER_CUBIC_METER = 1000.0
SECONDS_PER_HOUR = 3600.0
KJ_PER_KWH = 3600.0
KWH_TO_MJ = 3.6

SQRT_3 = sqrt(3)
PI = pi
WATER_SPECIFIC_HEAT_KJ_PER_KG_C = 4.186
WATER_HEAT_WH_PER_LITER_C = (WATER_SPECIFIC_HEAT_KJ_PER_KG_C * WATER_DENSITY / LITERS_PER_CUBIC_METER) / KJ_PER_KWH * 1000
