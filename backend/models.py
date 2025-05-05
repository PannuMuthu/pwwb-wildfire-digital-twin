from pydantic import BaseModel

class WindVector(BaseModel):
    speed: float
    direction: float
