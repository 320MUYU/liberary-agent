from pydantic import BaseModel,ConfigDict

class LoginRequest(BaseModel):
    username:str
    password:str