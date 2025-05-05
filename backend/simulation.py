from datetime import datetime, timedelta
import numpy as np
from typing import List, Tuple, Dict
import xarray as xr
import requests
import json
import os
from dataclasses import dataclass
from bs4 import BeautifulSoup
from models import WindVector
from hysplitdata_module import HYSPLITData

@dataclass
class SimulationConfig:
    start_location: Tuple[float, float]  # [lon, lat]
    start_time: datetime
    duration_hours: int = 24
    time_step_minutes: int = 30
    initial_polygon: List[List[float]] = None  # Initial fire polygon coordinates
    initial_wind: WindVector = None  # Initial wind conditions

class FireSimulation:
    def __init__(self, config: SimulationConfig):
        self.config = config
        self.hrrr_data = None
        self.hysplit_data = None

    async def fetch_hrrr_data(self):
        """
        Fetch HRRR meteorological data
        """
        lat = self.config.start_location[1]
        lon = self.config.start_location[0]
        url = f"https://api.weather.gov/points/{lat},{lon}"

        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        forecast_url = data["properties"]["forecastHourly"]
        forecast_response = requests.get(forecast_url)
        forecast_response.raise_for_status()
        forecast_data = forecast_response.json()

        wind_speed = []
        wind_direction = []
        temperature = []
        humidity = []

        for period in forecast_data["properties"]["periods"]:
            wind_speed.append(period["windSpeed"])
            wind_direction.append(period["windDirection"])
            temperature.append(period["temperature"])
            humidity.append(period["relativeHumidity"])

        for i in range(len(wind_speed)):
            wind_speed[i] = float(wind_speed[i][:-4])

        direction_map = {
            "": 0,
            "N": 0,
            "NNE": 22.5,
            "NE": 45,
            "ENE": 67.5,
            "E": 90,
            "ESE": 112.5,
            "SE": 135,
            "SSE": 157.5,
            "S": 180,
            "SSW": 202.5,
            "SW": 225,
            "WSW": 247.5,
            "W": 270,
            "WNW": 292.5,
            "NW": 315,
            "NNW": 337.5
        }
        for i in range(len(wind_direction)):
            wind_direction[i] = direction_map[wind_direction[i]]

        for i in range(len(humidity)):
            humidity[i] = humidity[i]["value"]

        self.hrrr_data = {
            "times": [datetime.fromisoformat(period["startTime"]) for period in forecast_data["properties"]["periods"]],
            "wind_speed": wind_speed,
            "wind_direction": wind_direction,
            "temperature": temperature,
            "humidity": humidity
        }

    async def run_hysplit(self):
        """
        Run the HYSPLIT simulation
        """
        # Get the extend box for the LA County area
        lat_bottom, lat_top = 33.9, 34.2
        lon_bottom, lon_top = -118.4, -118.0
        extent = (lon_bottom, lon_top, lat_bottom, lat_top)

        # Get HYSPLIT base directory
        base_dir = os.path.abspath("./hysplit")

        # Setup the hysplit simulation with the HYSPLITData class
        hysplit_data = HYSPLITData(
            self.config.start_location,
            self.config.start_time.strftime("%Y-%m-%d-%H"),
            (self.config.start_time + timedelta(hours=self.config.duration_hours)).strftime("%Y-%m-%d-%H"),
            extent,
            base_dir,
            os.path.abspath("."),
            os.path.join(base_dir, "exec"),
            os.path.join(base_dir, "bdyfiles"),
            os.path.join(base_dir, "output"),
            "gdas1.jan25.w2" # TODO: Make this live data
        )

        print(hysplit_data.data)

        # TODO: Return the smallest polygon that encloses the points

        # filler data
        self.hysplit_data = []
        for i in range(len(self.hrrr_data['times'])):
            self.hysplit_data.append({
                "coordinates": self.config.initial_polygon
            })

    def calculate_fire_spread(self) -> List[Dict]:
        """
        Calculate fire spread based on weather conditions and terrain
        """
        if not self.hrrr_data:
            return []

        spread_data = []
        
        # Use initial polygon if provided, otherwise use a point-based spread
        initial_coords = (
            self.config.initial_polygon 
            if self.config.initial_polygon 
            else [[self.config.start_location[0], self.config.start_location[1]]]
        )
        
        for i, time in enumerate(self.hrrr_data['times']):
            wind_speed = self.hrrr_data['wind_speed'][i]
            wind_dir = np.radians(self.hrrr_data['wind_direction'][i])
            temp = self.hrrr_data['temperature'][i]
            humidity = self.hrrr_data['humidity'][i]
            
            # Calculate spread rate based on conditions
            # Increase the influence of wind speed on spread rate
            base_spread = 0.002 * (1 + wind_speed/5) * (1 + (30-humidity)/50)
            
            if i == 0 and self.config.initial_polygon:
                # For the first timestep, use the initial polygon
                perimeter = initial_coords + [initial_coords[0]]  # Close the polygon
            else:
                # For subsequent timesteps or if no initial polygon, calculate spread
                # Create expanded perimeter based on previous perimeter or initial point
                prev_coords = spread_data[i-1]['coordinates'][0][:-1] if i > 0 else initial_coords
                perimeter = []
                
                for j, point in enumerate(prev_coords):
                    # Calculate the normal vector for this point
                    next_point = prev_coords[(j + 1) % len(prev_coords)]
                    prev_point = prev_coords[(j - 1) % len(prev_coords)]
                    
                    # Calculate vectors
                    v1 = np.array([next_point[0] - point[0], next_point[1] - point[1]])
                    v2 = np.array([point[0] - prev_point[0], point[1] - prev_point[1]])
                    
                    # Safely normalize vectors
                    v1_norm = np.zeros(2)
                    v2_norm = np.zeros(2)
                    
                    v1_length = np.linalg.norm(v1)
                    v2_length = np.linalg.norm(v2)
                    
                    if v1_length > 1e-10:  # Check if vector is not too close to zero
                        v1_norm = v1 / v1_length
                    if v2_length > 1e-10:
                        v2_norm = v2 / v2_length
                    
                    # Calculate normal vector (average of perpendicular vectors)
                    normal = np.array([-v1_norm[1] + -v2_norm[1], v1_norm[0] + v2_norm[0]])
                    normal_length = np.linalg.norm(normal)
                    
                    if normal_length > 1e-10:
                        normal = normal / normal_length
                    else:
                        # If normal is too small, use a default direction based on wind
                        normal = np.array([np.cos(wind_dir), np.sin(wind_dir)])
                    
                    # Calculate spread direction (combine normal with wind direction)
                    wind_vector = np.array([np.cos(wind_dir), np.sin(wind_dir)])
                    # Increase wind influence on spread direction
                    spread_dir = normal * 0.5 + wind_vector * 0.5  # More wind influence
                    spread_length = np.linalg.norm(spread_dir)
                    
                    if spread_length > 1e-10:
                        spread_dir = spread_dir / spread_length
                    else:
                        spread_dir = wind_vector  # Fallback to wind direction
                    
                    # Calculate new point position with wind speed influence
                    spread_distance = min(base_spread * (1 + wind_speed * 0.2), 0.1)  # Wind affects spread rate
                    new_point = [
                        float(point[0] + spread_dir[0] * spread_distance),  # Ensure float type
                        float(point[1] + spread_dir[1] * spread_distance)   # Ensure float type
                    ]
                    perimeter.append(new_point)
                
                # Close the polygon
                perimeter.append(perimeter[0])
            
            spread_data.append({
                'timestamp': time.isoformat(),
                'coordinates': [perimeter]
            })
        
        return spread_data

    async def run_simulation(self) -> List[Dict]:
        """
        Run the complete fire spread and smoke dispersion simulation
        """
        await self.fetch_hrrr_data()
        await self.run_hysplit()
        fire_spread = self.calculate_fire_spread()
        
        simulation_data = []
        for i, time in enumerate(self.hrrr_data['times']):
            simulation_data.append({
                'timestamp': time.isoformat(),
                'firePerimeter': {
                    'type': 'Feature',
                    'geometry': {
                        'type': 'Polygon',
                        'coordinates': fire_spread[i]['coordinates']
                    },
                    'properties': {}
                },
                'smokePlume': {
                    'type': 'Feature',
                    'geometry': {
                        'type': 'Polygon',
                        'coordinates': self.hysplit_data[i]['coordinates']
                    },
                    'properties': {}
                }
            })
        
        return simulation_data 
