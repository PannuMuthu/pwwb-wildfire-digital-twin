from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import numpy as np
from typing import List, Tuple, Dict
from simulation import SimulationConfig, FireSimulation

app = FastAPI(title="PWWB Fire Simulation API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Frontend dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class WindVector(BaseModel):
    speed: float       # m/s
    direction: float   # degrees from north

class SimulationRequest(BaseModel):
    start_point: Tuple[float, float]  # [lon, lat]
    start_time: datetime
    duration_hours: int = 24
    time_step_minutes: int = 30
    initial_polygon: List[List[float]]  # List of [lon, lat] coordinates forming the polygon
    initial_wind: WindVector

class SimulationResponse(BaseModel):
    simulation_data: List[dict]
    message: str

@app.post("/api/simulate", response_model=SimulationResponse)
async def run_simulation(req: SimulationRequest):
    try:
        config = SimulationConfig(
            start_location=req.start_point,
            start_time=req.start_time,
            duration_hours=req.duration_hours,
            time_step_minutes=req.time_step_minutes,
            initial_polygon=req.initial_polygon,
            initial_wind=req.initial_wind
        )
        
        simulation = FireSimulation(config)
        simulation_data = await simulation.run_simulation()
        
        return SimulationResponse(
            simulation_data=simulation_data,
            message="Simulation completed successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 