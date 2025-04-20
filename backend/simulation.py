from datetime import datetime, timedelta
import numpy as np
from typing import List, Tuple, Dict
import xarray as xr
import requests
import json
import os
from dataclasses import dataclass
from main import WindVector  # Import the WindVector type

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
        Fetch HRRR meteorological data from NOAA's API
        """
        # TODO: Implement actual HRRR API call
        # For now, using placeholder wind data with initial conditions
        times = [
            self.config.start_time + timedelta(minutes=i * self.config.time_step_minutes)
            for i in range(int(self.config.duration_hours * 60 / self.config.time_step_minutes))
        ]
        
        # Use initial wind conditions and add some variation over time
        base_speed = self.config.initial_wind.speed if self.config.initial_wind else 10
        base_direction = self.config.initial_wind.direction if self.config.initial_wind else 0
        
        # Generate wind data with some natural variation around the initial conditions
        wind_speeds = []
        wind_directions = []
        
        for _ in range(len(times)):
            # Add random variations to wind speed (±30% of base speed)
            speed_variation = np.random.uniform(-0.3, 0.3) * base_speed
            wind_speeds.append(base_speed + speed_variation)
            
            # Add random variations to wind direction (±30 degrees)
            dir_variation = np.random.uniform(-30, 30)
            wind_directions.append((base_direction + dir_variation) % 360)
        
        self.hrrr_data = {
            'times': times,
            'wind_speed': np.array(wind_speeds),
            'wind_direction': np.array(wind_directions),
            'temperature': np.random.uniform(20, 30, len(times)),  # Celsius
            'humidity': np.random.uniform(20, 60, len(times))  # %
        }

    async def run_hysplit(self):
        """
        Run HYSPLIT model for smoke dispersion
        """
        # TODO: Implement actual HYSPLIT API call
        # For now, generate simplified smoke plume shapes
        if not self.hrrr_data:
            await self.fetch_hrrr_data()

        self.hysplit_data = []
        lon, lat = self.config.start_location

        for i, time in enumerate(self.hrrr_data['times']):
            wind_speed = self.hrrr_data['wind_speed'][i]
            wind_dir = np.radians(self.hrrr_data['wind_direction'][i])
            
            # Calculate smoke plume direction and spread
            dx = wind_speed * np.cos(wind_dir) * i * 0.01
            dy = wind_speed * np.sin(wind_dir) * i * 0.01
            
            # Create a simple triangle-shaped plume
            plume_coords = [
                [lon, lat],
                [lon + dx - dy*0.3, lat + dy + dx*0.3],
                [lon + dx + dy*0.3, lat + dy - dx*0.3],
            ]
            
            self.hysplit_data.append({
                'timestamp': time.isoformat(),
                'coordinates': [plume_coords]
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