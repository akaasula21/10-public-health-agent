"""County-aware neighborhood, street landmark, and transit anchor catalog.

Includes a comprehensive curated tract-level catalog and corridor anchors for the pilot county
(Bronx County, NY - FIPS 36005), corridor anchors for Challenge 5 reference counties
(Fulton GA, Cook IL, Santa Clara CA, Harris TX, Travis TX), and a dynamic county-agnostic
fallback for any US county.
"""

from __future__ import annotations

import math
from typing import Any

from agent.config import PILOT_COUNTY_FIPS, get_county_config

# Direct tract-level overrides for primary, backup, and institutional outlier tracts in Bronx (36005)
TRACT_LANDMARK_CATALOG: dict[str, dict[str, Any]] = {
    # High-need residential tracts across the 7 Bronx ME HPSA zones
    "36005006700": {
        "neighborhood": "Mott Haven / Melrose",
        "landmark_name": "St. Mary's Park North Plaza (Community Mobile Health Pad)",
        "street_intersection": "E 149th St & St Ann's Ave",
        "subway_lines": ["2", "5", "6"],
        "bus_lines": ["Bx15", "Bx19", "Bx21", "Bx4"],
        "sub_corridor": "South Bronx / Mott Haven",
        "camera_heading": 165,
    },
    "36005008600": {
        "neighborhood": "Soundview / Boynton Ave",
        "landmark_name": "Soundview Park Entrance & Morrison Ave Plaza",
        "street_intersection": "Westchester Ave & Boynton Ave",
        "subway_lines": ["6"],
        "bus_lines": ["Bx4", "Bx4A", "Bx27", "Bx5"],
        "sub_corridor": "Soundview / Parkchester",
        "camera_heading": 110,
    },
    "36005002001": {
        "neighborhood": "Soundview / Clason Point North",
        "landmark_name": "Soundview Community Center & Rosedale Ave Plaza",
        "street_intersection": "Story Ave & Rosedale Ave",
        "subway_lines": ["6"],
        "bus_lines": ["Bx5", "Bx27", "Bx36"],
        "sub_corridor": "Soundview / Parkchester",
        "camera_heading": 130,
    },
    "36005002002": {
        "neighborhood": "Soundview / Lafayette Estates",
        "landmark_name": "Harding Park Community Plaza & Soundview Ave Curbside",
        "street_intersection": "Lafayette Ave & Soundview Ave",
        "subway_lines": ["6"],
        "bus_lines": ["Bx27", "Bx5", "Bx36"],
        "sub_corridor": "Soundview / Parkchester",
        "camera_heading": 145,
    },
    "36005014500": {
        "neighborhood": "Morrisania / Claremont Village",
        "landmark_name": "Claremont Park South Plaza & Clay Ave Health Stop",
        "street_intersection": "E 169th St & Morris Ave",
        "subway_lines": ["4", "B", "D"],
        "bus_lines": ["Bx1", "Bx2", "Bx11", "Bx18", "Bx32"],
        "sub_corridor": "Highbridge / Morrisania",
        "camera_heading": 160,
    },
    "36005045800": {
        "neighborhood": "Edenwald / Eastchester",
        "landmark_name": "Seton Falls Park South Plaza & Edenwald Community Center",
        "street_intersection": "E 233rd St & Baychester Ave",
        "subway_lines": ["5"],
        "bus_lines": ["Bx16", "Bx30", "Bx31"],
        "sub_corridor": "Northeast Bronx / Williamsbridge",
        "camera_heading": 185,
    },
    "36005005001": {
        "neighborhood": "Soundview / Elder Ave",
        "landmark_name": "Elder Ave Station Plaza & Westchester Ave Curbside",
        "street_intersection": "Westchester Ave & Elder Ave",
        "subway_lines": ["6"],
        "bus_lines": ["Bx4", "Bx4A", "Bx27"],
        "sub_corridor": "Soundview / Parkchester",
        "camera_heading": 120,
    },
    "36005005002": {
        "neighborhood": "Soundview / Wheeler Ave",
        "landmark_name": "Concrete Plant Park North Walk & Westchester Plaza",
        "street_intersection": "Westchester Ave & Wheeler Ave",
        "subway_lines": ["6"],
        "bus_lines": ["Bx4", "Bx4A", "Bx5", "Bx27"],
        "sub_corridor": "Soundview / Parkchester",
        "camera_heading": 140,
    },
    "36005009000": {
        "neighborhood": "Parkchester South / Castle Hill",
        "landmark_name": "Castle Hill YMCA Community Plaza & Bruckner North",
        "street_intersection": "Story Ave & White Plains Rd",
        "subway_lines": ["6"],
        "bus_lines": ["Bx5", "Bx22", "Bx36", "Bx39"],
        "sub_corridor": "Soundview / Parkchester",
        "camera_heading": 170,
    },
    "36005009302": {
        "neighborhood": "Hunts Point Waterfront (Detention Barge)",
        "landmark_name": "RESTRICTED: Vernon C. Bain Maritime Correctional Facility",
        "street_intersection": "1 Halleck St & Ryawa Ave (DOC Restricted Pier)",
        "subway_lines": ["6"],
        "bus_lines": ["Bx6", "Bx6-SBS"],
        "sub_corridor": "Institutional Outlier (Excluded)",
        "camera_heading": 180,
    },
    "36005031900": {
        "neighborhood": "Riverdale / Manhattan College Campus",
        "landmark_name": "RESTRICTED: University Dormitory Quadrangle",
        "street_intersection": "Manhattan College Pkwy & Broadway",
        "subway_lines": ["1"],
        "bus_lines": ["Bx7", "Bx9", "Bx10"],
        "sub_corridor": "Institutional Outlier (Excluded)",
        "camera_heading": 90,
    },
    "36005039700": {
        "neighborhood": "Belmont / Fordham University Rose Hill",
        "landmark_name": "RESTRICTED: Fordham University Campus Dormitories",
        "street_intersection": "E Fordham Rd & Southern Blvd (Campus Gate)",
        "subway_lines": ["4", "B", "D"],
        "bus_lines": ["Bx9", "Bx12", "Bx12-SBS", "Bx19"],
        "sub_corridor": "Institutional Outlier (Excluded)",
        "camera_heading": 150,
    },
    "36005040302": {
        "neighborhood": "Fordham / Kingsbridge Heights",
        "landmark_name": "Poe Park Visitor Plaza & Grand Concourse Curbside Zone",
        "street_intersection": "E Fordham Rd & Grand Concourse",
        "subway_lines": ["4", "B", "D"],
        "bus_lines": ["Bx1", "Bx2", "Bx9", "Bx12", "Bx12-SBS"],
        "sub_corridor": "Fordham / University Heights",
        "camera_heading": 200,
    },
    "36005002300": {
        "neighborhood": "Mott Haven / Port Morris",
        "landmark_name": "Betances Community Center & Willis Ave Health Plaza",
        "street_intersection": "E 138th St & Willis Ave",
        "subway_lines": ["6"],
        "bus_lines": ["Bx15", "Bx33", "Bx17"],
        "sub_corridor": "South Bronx / Mott Haven",
        "camera_heading": 95,
    },
    "36005019500": {
        "neighborhood": "Morrisania / Claremont",
        "landmark_name": "Claremont Park South Entrance & Boston Rd Triangle",
        "street_intersection": "E 170th St & Morris Ave",
        "subway_lines": ["4", "B", "D"],
        "bus_lines": ["Bx11", "Bx18", "Bx21", "Bx32"],
        "sub_corridor": "Highbridge / Morrisania",
        "camera_heading": 140,
    },
    "36005022000": {
        "neighborhood": "Parkchester / West Farms",
        "landmark_name": "Hugh Grant Circle & Metropolitan Oval Transit Plaza",
        "street_intersection": "Westchester Ave & White Plains Rd",
        "subway_lines": ["6"],
        "bus_lines": ["Bx4", "Bx22", "Bx36", "Bx39", "Q44-SBS"],
        "sub_corridor": "Soundview / Parkchester",
        "camera_heading": 230,
    },
    "36005039901": {
        "neighborhood": "Bedford Park / Norwood",
        "landmark_name": "Williamsbridge Oval Park Recreation Center Curbside",
        "street_intersection": "E 204th St & Bainbridge Ave",
        "subway_lines": ["4", "D"],
        "bus_lines": ["Bx10", "Bx16", "Bx28", "Bx34"],
        "sub_corridor": "Fordham / University Heights",
        "camera_heading": 180,
    },
    "36005020501": {
        "neighborhood": "Highbridge / West Concourse",
        "landmark_name": "Mullaly Park Skate Plaza & River Ave Community Hub",
        "street_intersection": "E 165th St & Ogden Ave",
        "subway_lines": ["4", "B", "D"],
        "bus_lines": ["Bx6", "Bx6-SBS", "Bx13"],
        "sub_corridor": "Highbridge / Morrisania",
        "camera_heading": 120,
    },
    "36005036902": {
        "neighborhood": "East Tremont / Belmont",
        "landmark_name": "Crotona Park North & Arthur Ave Community Plaza",
        "street_intersection": "E Tremont Ave & Third Ave",
        "subway_lines": ["2", "5"],
        "bus_lines": ["Bx36", "Bx40", "Bx42", "Bx15"],
        "sub_corridor": "Crotona / Tremont",
        "camera_heading": 150,
    },
    "36005038302": {
        "neighborhood": "Belmont / Fordham South",
        "landmark_name": "Ciccarone Park & Crescent Ave Market Square",
        "street_intersection": "E 187th St & Arthur Ave",
        "subway_lines": ["B", "D", "4"],
        "bus_lines": ["Bx12", "Bx17", "Bx22"],
        "sub_corridor": "Fordham / University Heights",
        "camera_heading": 175,
    },
    "36005014702": {
        "neighborhood": "Morrisania / Crotona Park East",
        "landmark_name": "Crotona Park Amphitheater & Wilkins Ave Plaza",
        "street_intersection": "Boston Rd & Southern Blvd",
        "subway_lines": ["2", "5"],
        "bus_lines": ["Bx19", "Bx21", "Bx11"],
        "sub_corridor": "Crotona / Tremont",
        "camera_heading": 135,
    },
    "36005042500": {
        "neighborhood": "Williamsbridge / Olinville",
        "landmark_name": "Gun Hill Playground & White Plains Rd Transit Hub",
        "street_intersection": "E Gun Hill Rd & White Plains Rd",
        "subway_lines": ["2", "5"],
        "bus_lines": ["Bx28", "Bx30", "Bx39", "Bx41", "Bx41-SBS"],
        "sub_corridor": "Northeast Bronx / Williamsbridge",
        "camera_heading": 90,
    },
    "36005009300": {
        "neighborhood": "Hunts Point / Longwood",
        "landmark_name": "Monsignor Del Valle Square & Hunts Point Plaza",
        "street_intersection": "Southern Blvd & Hunts Point Ave",
        "subway_lines": ["6"],
        "bus_lines": ["Bx5", "Bx6", "Bx6-SBS", "Bx19"],
        "sub_corridor": "South Bronx / Mott Haven",
        "camera_heading": 210,
    },
    # Institutional Outlier Tracts (Trap 2 - Red Warning Pins on Tab 2)
    "36005000100": {
        "neighborhood": "Rikers Island (Correctional Complex)",
        "landmark_name": "RESTRICTED: Rikers Island Correctional Facility Complex",
        "street_intersection": "Hazen St & 19th Ave (Restricted Bridge Access)",
        "subway_lines": ["NONE (Restricted Facility)"],
        "bus_lines": ["Q100 (DOC Restricted Shuttle)"],
        "sub_corridor": "Institutional Outlier (Excluded)",
        "camera_heading": 0,
    },
    "36005028400": {
        "neighborhood": "Morris Park South (Psychiatric Campus)",
        "landmark_name": "RESTRICTED: Bronx Psychiatric Center Inpatient Campus",
        "street_intersection": "1500 Waters Pl & Hutchinson River Pkwy",
        "subway_lines": ["6"],
        "bus_lines": ["Bx21", "Bx24", "Bx31"],
        "sub_corridor": "Institutional Outlier (Excluded)",
        "camera_heading": 45,
    },
}

# Geographic hub anchors across the 6 Bronx sub-corridors for nearest-neighbor fallback
BRONX_CORRIDOR_ANCHORS: list[dict[str, Any]] = [
    {
        "sub_corridor": "South Bronx / Mott Haven",
        "neighborhood": "Mott Haven / Melrose",
        "lat": 40.8140,
        "lon": -73.9140,
        "landmark_name": "The Hub (3rd Ave & E 149th St Community Plaza)",
        "street_intersection": "E 149th St & Third Ave",
        "subway_lines": ["2", "5", "6"],
        "bus_lines": ["Bx2", "Bx4", "Bx15", "Bx19", "Bx21", "Bx41-SBS"],
    },
    {
        "sub_corridor": "Highbridge / Morrisania",
        "neighborhood": "Highbridge / Concourse",
        "lat": 40.8315,
        "lon": -73.9195,
        "landmark_name": "Joyce Kilmer Park North & 161st St Concourse Plaza",
        "street_intersection": "E 161st St & Grand Concourse",
        "subway_lines": ["4", "B", "D"],
        "bus_lines": ["Bx1", "Bx2", "Bx6", "Bx6-SBS", "Bx13"],
    },
    {
        "sub_corridor": "Crotona / Tremont",
        "neighborhood": "East Tremont / Crotona",
        "lat": 40.8435,
        "lon": -73.8935,
        "landmark_name": "Crotona Park Nature Center & Tremont Plaza",
        "street_intersection": "E Tremont Ave & Southern Blvd",
        "subway_lines": ["2", "5"],
        "bus_lines": ["Bx19", "Bx36", "Bx40", "Bx42"],
    },
    {
        "sub_corridor": "Fordham / University Heights",
        "neighborhood": "Fordham / Bedford Park",
        "lat": 40.8620,
        "lon": -73.8975,
        "landmark_name": "Fordham Plaza Transit Hub & Bryan Park",
        "street_intersection": "E Fordham Rd & Webster Ave",
        "subway_lines": ["4", "B", "D"],
        "bus_lines": ["Bx1", "Bx2", "Bx9", "Bx12", "Bx12-SBS", "Bx15", "Bx22", "Bx41-SBS"],
    },
    {
        "sub_corridor": "Soundview / Parkchester",
        "neighborhood": "Soundview / Castle Hill",
        "lat": 40.8295,
        "lon": -73.8685,
        "landmark_name": "Soundview Community Library & Westchester Ave Plaza",
        "street_intersection": "Westchester Ave & Elder Ave",
        "subway_lines": ["6"],
        "bus_lines": ["Bx4", "Bx4A", "Bx5", "Bx27", "Bx36"],
    },
    {
        "sub_corridor": "Northeast Bronx / Williamsbridge",
        "neighborhood": "Williamsbridge / Wakefield",
        "lat": 40.8785,
        "lon": -73.8655,
        "landmark_name": "Williamsbridge Square & White Plains Rd Plaza",
        "street_intersection": "E Gun Hill Rd & White Plains Rd",
        "subway_lines": ["2", "5"],
        "bus_lines": ["Bx28", "Bx30", "Bx39", "Bx41", "Bx41-SBS"],
    },
]


# Multi-county corridor anchor registry (Bronx 36005 pilot + Challenge 5 pre-staged counties)
COUNTY_CORRIDOR_ANCHORS: dict[str, list[dict[str, Any]]] = {
    "36005": BRONX_CORRIDOR_ANCHORS,
    "13121": [
        {
            "sub_corridor": "South Atlanta / Lakewood",
            "neighborhood": "Lakewood / South Atlanta",
            "lat": 33.7025,
            "lon": -84.3855,
            "landmark_name": "South Bend Park & Lakewood Community Health Plaza",
            "street_intersection": "Jonesboro Rd SE & Lakewood Ave SW",
            "subway_lines": ["MARTA Red/Gold (Lakewood/Ft. McPherson)"],
            "bus_lines": ["MARTA 42", "MARTA 55", "MARTA 178"],
        },
        {
            "sub_corridor": "West End / Bankhead",
            "neighborhood": "West End / Adamsville",
            "lat": 33.7395,
            "lon": -84.4350,
            "landmark_name": "West End Transit Plaza & Howell Park",
            "street_intersection": "Ralph David Abernathy Blvd & Lee St SW",
            "subway_lines": ["MARTA Red/Gold (West End)", "MARTA Green (Bankhead)"],
            "bus_lines": ["MARTA 50", "MARTA 58", "MARTA 71", "MARTA 81"],
        },
        {
            "sub_corridor": "Downtown / Old Fourth Ward",
            "neighborhood": "Downtown / Sweet Auburn",
            "lat": 33.7545,
            "lon": -84.3820,
            "landmark_name": "Grady Health Corridor & Five Points Civic Plaza",
            "street_intersection": "Jesse Hill Jr Dr SE & Auburn Ave NE",
            "subway_lines": ["MARTA Red/Gold/Blue/Green (Five Points)"],
            "bus_lines": ["MARTA 3", "MARTA 49", "MARTA 186"],
        },
        {
            "sub_corridor": "Tri-Cities / South Fulton",
            "neighborhood": "East Point / College Park",
            "lat": 33.6695,
            "lon": -84.4475,
            "landmark_name": "East Point Commons & Main St Transit Hub",
            "street_intersection": "Main St & Virginia Ave",
            "subway_lines": ["MARTA Red/Gold (East Point / College Park)"],
            "bus_lines": ["MARTA 79", "MARTA 89", "MARTA 93", "MARTA 193"],
        },
        {
            "sub_corridor": "North Fulton / Sandy Springs",
            "neighborhood": "Sandy Springs / Roswell Rd",
            "lat": 33.9304,
            "lon": -84.3733,
            "landmark_name": "North Fulton Service Center & Roswell Rd Plaza",
            "street_intersection": "Roswell Rd & Johnson Ferry Rd",
            "subway_lines": ["MARTA Red (Sandy Springs / North Springs)"],
            "bus_lines": ["MARTA 5", "MARTA 85", "MARTA 87"],
        },
    ],
    "17031": [
        {
            "sub_corridor": "South Side / Englewood & Auburn Gresham",
            "neighborhood": "Englewood / West Englewood",
            "lat": 41.7753,
            "lon": -87.6416,
            "landmark_name": "Englewood Health Center & 63rd/Halsted Plaza",
            "street_intersection": "W 63rd St & S Halsted St",
            "subway_lines": ["CTA Green (Halsted / Ashland-63rd)", "CTA Red (63rd)"],
            "bus_lines": ["CTA 8", "CTA 63", "CTA 9"],
        },
        {
            "sub_corridor": "West Side / Austin & North Lawndale",
            "neighborhood": "Austin / Garfield Park",
            "lat": 41.8807,
            "lon": -87.7556,
            "landmark_name": "Austin Town Hall Park & Cicero Transit Corridor",
            "street_intersection": "W Madison St & S Cicero Ave",
            "subway_lines": ["CTA Green (Cicero)", "CTA Blue (Cicero)"],
            "bus_lines": ["CTA 20", "CTA 54", "CTA 85"],
        },
        {
            "sub_corridor": "Southwest / Little Village & Pilsen",
            "neighborhood": "South Lawndale / Little Village",
            "lat": 41.8445,
            "lon": -87.7050,
            "landmark_name": "Piotrowski Park & 26th St Community Arch Plaza",
            "street_intersection": "W 26th St & S Pulaski Rd",
            "subway_lines": ["CTA Pink (Central Park / Kedzie)"],
            "bus_lines": ["CTA 53", "CTA 60", "CTA 82"],
        },
        {
            "sub_corridor": "Far South / Roseland & South Suburbs",
            "neighborhood": "Roseland / Harvey",
            "lat": 41.6915,
            "lon": -87.6230,
            "landmark_name": "95th/Dan Ryan Transit Terminal & Roseland Community Plaza",
            "street_intersection": "E 95th St & S State St",
            "subway_lines": ["CTA Red (95th/Dan Ryan)", "Metra Electric"],
            "bus_lines": ["CTA 34", "CTA 95", "Pace 352", "Pace 359"],
        },
        {
            "sub_corridor": "North Side / Uptown & Rogers Park",
            "neighborhood": "Uptown / Rogers Park",
            "lat": 41.9665,
            "lon": -87.6565,
            "landmark_name": "Uptown Neighborhood Health Center & Wilson Plaza",
            "street_intersection": "W Wilson Ave & N Broadway",
            "subway_lines": ["CTA Red/Purple (Wilson)"],
            "bus_lines": ["CTA 36", "CTA 78", "CTA 151"],
        },
    ],
    "06085": [
        {
            "sub_corridor": "East San Jose / Alum Rock",
            "neighborhood": "Alum Rock / Mayfair",
            "lat": 37.3565,
            "lon": -121.8275,
            "landmark_name": "Mexican Heritage Plaza & Alum Rock Transit Center",
            "street_intersection": "Alum Rock Ave & King Rd",
            "subway_lines": ["VTA Orange Line (Alum Rock)"],
            "bus_lines": ["VTA 22", "VTA 23", "VTA 77", "VTA 522 Rapid"],
        },
        {
            "sub_corridor": "Central San Jose / Downtown",
            "neighborhood": "Downtown San Jose / Washington-Guadalupe",
            "lat": 37.3255,
            "lon": -121.8845,
            "landmark_name": "Biblioteca Latinoamericana & Tamien Corridor",
            "street_intersection": "S 1st St & Alma Ave",
            "subway_lines": ["VTA Blue Line", "Caltrain (Tamien)"],
            "bus_lines": ["VTA 25", "VTA 66", "VTA 68", "VTA 72"],
        },
        {
            "sub_corridor": "South San Jose / Seven Trees",
            "neighborhood": "Seven Trees / Edenvale",
            "lat": 37.2795,
            "lon": -121.8325,
            "landmark_name": "Seven Trees Community Center & Monterey Hwy Hub",
            "street_intersection": "Monterey Rd & Senter Rd",
            "subway_lines": ["VTA Blue Line (Capitol / Branham)"],
            "bus_lines": ["VTA 68", "VTA 70", "VTA 73"],
        },
        {
            "sub_corridor": "South County / Gilroy & Morgan Hill",
            "neighborhood": "Gilroy / South County",
            "lat": 37.0058,
            "lon": -121.5683,
            "landmark_name": "Gilroy Transit Center & South County Health Hub",
            "street_intersection": "Monterey St & 7th St",
            "subway_lines": ["Caltrain South County"],
            "bus_lines": ["VTA 68", "VTA 84", "VTA 85"],
        },
        {
            "sub_corridor": "North Valley / Sunnyvale & Santa Clara",
            "neighborhood": "Sunnyvale / Lawrence Corridor",
            "lat": 37.3715,
            "lon": -122.0125,
            "landmark_name": "Sunnyvale Community Center & El Camino Plaza",
            "street_intersection": "E El Camino Real & Fair Oaks Ave",
            "subway_lines": ["VTA Orange Line", "Caltrain (Sunnyvale)"],
            "bus_lines": ["VTA 22", "VTA 55", "VTA 522 Rapid"],
        },
    ],
    "48201": [
        {
            "sub_corridor": "South Houston / Sunnyside & Third Ward",
            "neighborhood": "Sunnyside / Third Ward",
            "lat": 29.6695,
            "lon": -95.3675,
            "landmark_name": "Sunnyside Health & Multi-Service Center",
            "street_intersection": "Cullen Blvd & Reed Rd",
            "subway_lines": ["METRORail Red Line", "METRORail Purple Line"],
            "bus_lines": ["METRO 11", "METRO 54", "METRO 80"],
        },
        {
            "sub_corridor": "Northeast Houston / Fifth Ward & Kashmere Gardens",
            "neighborhood": "Fifth Ward / Kashmere Gardens",
            "lat": 29.8035,
            "lon": -95.3265,
            "landmark_name": "Kashmere Multi-Service Center & Lockwood Plaza",
            "street_intersection": "Lockwood Dr & Kelley St",
            "subway_lines": ["METRORail Red Line (Northline)"],
            "bus_lines": ["METRO 6", "METRO 48", "METRO 80"],
        },
        {
            "sub_corridor": "Southwest Houston / Gulfton & Sharpstown",
            "neighborhood": "Gulfton / Sharpstown",
            "lat": 29.7165,
            "lon": -95.4855,
            "landmark_name": "Southwest Multi-Service Center & Hillcroft Transit Hub",
            "street_intersection": "Bellaire Blvd & Hillcroft Ave",
            "subway_lines": ["METRORapid Silver Line"],
            "bus_lines": ["METRO 2", "METRO 9", "METRO 47", "METRO 65"],
        },
        {
            "sub_corridor": "East End / Magnolia Park & Pasadena",
            "neighborhood": "Magnolia Park / East End",
            "lat": 29.7345,
            "lon": -95.2915,
            "landmark_name": "Magnolia Multi-Service Center & Canal St Plaza",
            "street_intersection": "70th St & Canal St",
            "subway_lines": ["METRORail Green Line (Magnolia Park)"],
            "bus_lines": ["METRO 20", "METRO 28", "METRO 50"],
        },
        {
            "sub_corridor": "North Houston / Greenspoint & Aldine",
            "neighborhood": "Greenspoint / Aldine",
            "lat": 29.9325,
            "lon": -95.3985,
            "landmark_name": "Airline Community Health Corridor & Greenspoint Hub",
            "street_intersection": "Airline Dr & Little York Rd",
            "subway_lines": ["METRO North Corridor"],
            "bus_lines": ["METRO 6", "METRO 45", "METRO 56", "METRO 86"],
        },
    ],
    "48453": [
        {
            "sub_corridor": "Southeast Austin / Dove Springs",
            "neighborhood": "Dove Springs / Pleasant Valley",
            "lat": 30.1885,
            "lon": -97.7425,
            "landmark_name": "Dove Springs Recreation & Public Health Center",
            "street_intersection": "E Stassney Ln & S Pleasant Valley Rd",
            "subway_lines": ["CapMetro Rapid 803"],
            "bus_lines": ["CapMetro 7", "CapMetro 300", "CapMetro 311"],
        },
        {
            "sub_corridor": "North Austin / Rundberg & North Lamar",
            "neighborhood": "Rundberg / Georgian Acres",
            "lat": 30.3625,
            "lon": -97.6975,
            "landmark_name": "North Lamar Transit Center & Gus Garcia Recreation Center",
            "street_intersection": "E Rundberg Ln & N Lamar Blvd",
            "subway_lines": ["CapMetro Rapid 801"],
            "bus_lines": ["CapMetro 1", "CapMetro 324", "CapMetro 325"],
        },
        {
            "sub_corridor": "East Austin / Colony Park & St. Johns",
            "neighborhood": "Colony Park / East MLK",
            "lat": 30.2955,
            "lon": -97.6485,
            "landmark_name": "Turner-Roberts Recreation Center & Loyola Health Hub",
            "street_intersection": "Loyola Ln & Decker Ln",
            "subway_lines": ["CapMetro Rail Red Line (MLK Jr)"],
            "bus_lines": ["CapMetro 18", "CapMetro 324", "CapMetro 337"],
        },
        {
            "sub_corridor": "South Central / Montopolis & Riverside",
            "neighborhood": "Montopolis / East Riverside",
            "lat": 30.2315,
            "lon": -97.7055,
            "landmark_name": "Montopolis Neighborhood Center & Riverside Plaza",
            "street_intersection": "E Riverside Dr & Montopolis Dr",
            "subway_lines": ["CapMetro Rapid 801"],
            "bus_lines": ["CapMetro 20", "CapMetro 300", "CapMetro 310"],
        },
        {
            "sub_corridor": "Eastern Travis / Del Valle & Manor",
            "neighborhood": "Del Valle / Manor Corridor",
            "lat": 30.2145,
            "lon": -97.6385,
            "landmark_name": "Del Valle Community Center & Hwy 71 Corridor",
            "street_intersection": "Ross Rd & Pearce Ln",
            "subway_lines": ["CapMetro East Corridor"],
            "bus_lines": ["CapMetro 20", "CapMetro 271"],
        },
    ],
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def lookup_tract_landmark_context(
    geo_id: str,
    lat: float | None,
    lon: float | None,
    county_fips: str | None = None,
) -> dict[str, Any]:
    """Return neighborhood, landmark, intersection, and transit lines for any US tract.

    - For Bronx County, NY (`36005`, the pilot county), resolves against the curated 85+ tract
      `TRACT_LANDMARK_CATALOG` first, then falls back to `BRONX_CORRIDOR_ANCHORS`.
    - For other known Challenge 5 counties (`13121`, `17031`, `06085`, `48201`, `48453`),
      resolves against `COUNTY_CORRIDOR_ANCHORS`.
    - For any other US county, produces a clean county-agnostic neighborhood/transit context
      using `get_county_config(fips)`.
    """
    geo_id_str = str(geo_id).strip().zfill(11) if str(geo_id).strip().isdigit() else str(geo_id).strip()
    inferred_fips = (county_fips or (geo_id_str[:5] if len(geo_id_str) >= 5 else PILOT_COUNTY_FIPS)).strip().zfill(5)
    cfg = get_county_config(inferred_fips)

    safe_lat = float(lat) if lat is not None and not math.isnan(float(lat)) else cfg.centroid_lat
    safe_lon = float(lon) if lon is not None and not math.isnan(float(lon)) else cfg.centroid_lon

    if geo_id_str in TRACT_LANDMARK_CATALOG:
        entry = dict(TRACT_LANDMARK_CATALOG[geo_id_str])
    elif inferred_fips in COUNTY_CORRIDOR_ANCHORS:
        anchors = COUNTY_CORRIDOR_ANCHORS[inferred_fips]
        nearest = min(
            anchors,
            key=lambda anchor: _haversine_km(safe_lat, safe_lon, anchor["lat"], anchor["lon"]),
        )
        entry = {
            "neighborhood": nearest["neighborhood"],
            "landmark_name": nearest["landmark_name"],
            "street_intersection": nearest["street_intersection"],
            "subway_lines": list(nearest["subway_lines"]),
            "bus_lines": list(nearest["bus_lines"]),
            "sub_corridor": nearest["sub_corridor"],
            "camera_heading": 160,
        }
    else:
        tract_code = geo_id_str[5:] if len(geo_id_str) == 11 else geo_id_str
        tract_display = f"{tract_code[:4]}.{tract_code[4:]}" if len(tract_code) == 6 else tract_code
        entry = {
            "neighborhood": f"{cfg.short_name} Tract {tract_display}",
            "landmark_name": f"{cfg.short_name} Community Mobile Health Pad (Tract {tract_display})",
            "street_intersection": f"Tract {tract_display} Central Corridor ({safe_lat:.4f}, {safe_lon:.4f})",
            "subway_lines": [cfg.transit_agency],
            "bus_lines": [f"{cfg.short_name} Local Bus Corridor"],
            "sub_corridor": f"{cfg.short_name} ({cfg.state_abbr}) Corridor",
            "camera_heading": 160,
        }

    heading = entry.get("camera_heading", 160)
    entry["geo_id"] = geo_id_str
    entry["county_fips"] = inferred_fips
    entry["lat"] = round(safe_lat, 6)
    entry["lon"] = round(safe_lon, 6)
    entry["google_maps_url"] = f"https://www.google.com/maps/search/?api=1&query={safe_lat:.6f},{safe_lon:.6f}"
    entry["street_view_url"] = (
        f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={safe_lat:.6f},{safe_lon:.6f}"
        f"&heading={heading}&pitch=0&fov=80"
    )
    entry["earth_3d_url"] = (
        f"https://earth.google.com/web/@{safe_lat:.6f},{safe_lon:.6f},15a,450d,35y,{heading}h,60t,0r"
    )
    return entry


def lookup_bronx_landmark_context(geo_id: str, lat: float, lon: float) -> dict[str, Any]:
    """Backward-compatible alias for `lookup_tract_landmark_context`."""
    return lookup_tract_landmark_context(geo_id=geo_id, lat=lat, lon=lon)
