"""Fixed reference tables and constants used by the engine.

The country-name table is a draft. Plan section 5.4, decision 4 (who reviews
the mapping from country names to codes) is still open, so every name added
here should be checked by that reviewer.
"""

from __future__ import annotations

from datetime import date

ENGINE_VERSION = "0.1.0"
SCHEMA_VERSION = "1.1"

STUDY_START = date(2025, 1, 1)
STUDY_END = date(2026, 9, 30)

# ISO 3166-1 alpha-2, officially assigned codes.
ISO_COUNTRY_CODES = frozenset(
    """
    AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ
    BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR
    CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR
    GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU
    ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ
    LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ
    MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF
    PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI
    SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR
    TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
    """.split()
)

# Country names (normalised: case-folded, punctuation removed, whitespace
# collapsed) to ISO alpha-2. DRAFT, pending review (plan section 5.4, item 4).
COUNTRY_NAMES = {
    # Study countries and their common variants.
    "china": "CN",
    "peoples republic of china": "CN",
    "pr china": "CN",
    "prc": "CN",
    "mainland china": "CN",
    "hong kong": "HK",
    "hong kong sar": "HK",
    "hong kong sar china": "HK",
    "malaysia": "MY",
    "philippines": "PH",
    "the philippines": "PH",
    "republic of the philippines": "PH",
    "singapore": "SG",
    "republic of singapore": "SG",
    "taiwan": "TW",
    "taiwan province of china": "TW",
    "republic of china": "TW",
    "chinese taipei": "TW",
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "us": "US",
    "u s": "US",
    "america": "US",
    # Other trading countries seen in the graph's ports or likely in payloads.
    "viet nam": "VN",
    "vietnam": "VN",
    "south korea": "KR",
    "korea": "KR",
    "republic of korea": "KR",
    "korea republic of": "KR",
    "north korea": "KP",
    "japan": "JP",
    "thailand": "TH",
    "indonesia": "ID",
    "india": "IN",
    "cambodia": "KH",
    "myanmar": "MM",
    "burma": "MM",
    "laos": "LA",
    "brunei": "BN",
    "brunei darussalam": "BN",
    "bangladesh": "BD",
    "sri lanka": "LK",
    "pakistan": "PK",
    "macau": "MO",
    "macao": "MO",
    "australia": "AU",
    "new zealand": "NZ",
    "canada": "CA",
    "mexico": "MX",
    "brazil": "BR",
    "united kingdom": "GB",
    "great britain": "GB",
    "uk": "GB",
    "germany": "DE",
    "france": "FR",
    "italy": "IT",
    "spain": "ES",
    "netherlands": "NL",
    "the netherlands": "NL",
    "belgium": "BE",
    "ireland": "IE",
    "switzerland": "CH",
    "poland": "PL",
    "czech republic": "CZ",
    "czechia": "CZ",
    "hungary": "HU",
    "sweden": "SE",
    "turkey": "TR",
    "turkiye": "TR",
    "israel": "IL",
    "united arab emirates": "AE",
    "saudi arabia": "SA",
    "egypt": "EG",
    "south africa": "ZA",
    "panama": "PA",
    "iran": "IR",
    "russia": "RU",
    "russian federation": "RU",
}

# ISO 4217 active currency codes (precious metals and testing codes excluded).
ISO_CURRENCY_CODES = frozenset(
    """
    AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB
    BOV BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUP
    CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ
    GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW
    KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR
    MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN
    PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC
    SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI UYU UYW UZS
    VED VES VND VUV WST XAF XCD XCG XOF XPF YER ZAR ZMW ZWG
    """.split()
)

# Allowed values of entry_ports[].coast (plan section 6.1).
COASTS = frozenset({"west", "east_gulf"})

STRENGTH_RANK = {"strong": 3, "medium": 2, "weak": 1}

# Tie-break between bases of equal strength: the earlier basis is reported as
# the record's main link. Every link is still returned in `links`.
BASIS_PRIORITY = (
    "company_name",
    "parent_company_name",
    "buyer_name",
    "vessel_name",
    "carrier_name",
    "port_code",
    "hs_code",
    "port_name",
    "currency",
    "trade_lane",
    "country_code",
    "importing_country",
    "port_country",
)

# Date family for each risk type (plan section 7). Keys are the `risk_type`
# values stored in the database files.
DATE_FAMILY = {
    "supplier_operational_disruption": "event_interval",
    "cyberattack": "event_interval",
    "supplier_financial_distress": "observation_point",
    "product_quality_compliance": "event_interval",
    "labour_disruption": "event_interval",
    "natural_hazards": "event_interval",
    "port_disruption": "event_interval",
    "carrier_vessel_disruption": "event_interval",
    "route_chokepoint_disruption": "event_interval",
    "goods_in_transit_loss_theft_or_damage": "event_interval",
    "tariffs_and_duties": "effective_interval",
    "government_restrictions": "effective_interval",
    "border_customs_delays": "event_interval",
    "geopolitical_conflict": "event_interval",
    "input_material_shortage": "event_interval",
    "energy_or_transport_cost_increase": "observation_start",
    "supplier_or_route_concentration": "observation_start",
    "currency_fluctuations": "observation_start",
}

KNOWN_RISK_TYPES = frozenset(DATE_FAMILY)
