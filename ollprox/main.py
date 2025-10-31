import os
import json
import hashlib
import requests
import redis
import secrets
import random
import socket
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import StreamingResponse
import uvicorn
import time

app = FastAPI(title="Ollama Proxy", version="1.0.0")

# Get configuration from environment variables
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "ollama")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
OLLAMA_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"

SERVICE_PORT = int(os.getenv("EXTERNAL_PORT", "8000"))

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))  # Default 1 hour in seconds


class API_Key_Authenticator:

    def __init__(self):
        # API Key configuration
        self.API_KEY_FILE = "/api_keys.txt"
        self.API_KEY_SALT = os.getenv("API_KEY_SALT", "DEF"+str(secrets.token_urlsafe(16)))
        self.API_KEY_REFRESH_TIME = max([int(os.getenv("KEY_REFRESH",10)),2])
        self.already_salted = bool(os.getenv("API_KEY_SALT"))
        self.VALID_API_KEYS_SALTED = set()
        self.LAST_KEY_REFRESH = time.time()


        # Initialize valid API keys
        if self.API_KEY_FILE and os.path.exists(self.API_KEY_FILE):
            self.VALID_API_KEYS_SALTED = self.get_keys_from_file(self.API_KEY_FILE)

        if not self.VALID_API_KEYS_SALTED:
            # Generate a random API key if no file is provided, this is not secure for production
            random.seed(socket.gethostname())
            generated_key = ''.join(random.choice('0123456789abcdef') for _ in range(32))
            self.VALID_API_KEYS_SALTED.add(generated_key)
            print(f"[IMPORTANT] No API key file provided. Generated random API key: {generated_key}")


    def get_keys_from_file(self, file_path: str) -> set:
        self.LAST_KEY_REFRESH = time.time()
        all_keys = set()
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        if self.already_salted:
                            hashed_key = line
                        else:   
                            hashed_key = self.hash_api_key(line)
                        all_keys.add(hashed_key)
        except Exception as e:
            print(f"Error reading API key file: {e}")
        return all_keys

    def hash_api_key(self, key: str) -> str:
        """Hash an API key with salt using SHA256."""
        salted_key = f"{key}@separator@{self.API_KEY_SALT}"
        return hashlib.sha256(salted_key.encode()).hexdigest()

    def verify_api_key(self, api_key: str) -> bool:
        """Verify if the provided API key is valid."""
        hashed_key = self.hash_api_key(api_key)
        if not hashed_key:
            return False

        current_time = time.time()
        if current_time - self.LAST_KEY_REFRESH > self.API_KEY_REFRESH_TIME \
            or (not hashed_key in self.VALID_API_KEYS_SALTED):
            newkeys = self.get_keys_from_file(self.API_KEY_FILE)
            if newkeys:
                self.VALID_API_KEYS_SALTED = newkeys
            
        return hashed_key in self.VALID_API_KEYS_SALTED


authenticator = API_Key_Authenticator()

def get_cache_key(request: dict) -> str:
    """Generate a cache key based on the request payload."""
    request_str = json.dumps(request, sort_keys=True)
    return f"ollama_cache:{hashlib.md5(request_str.encode()).hexdigest()}"



# Initialize Redis client
try:
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
    redis_client.ping()
except Exception as e:
    print(f"Warning: Could not connect to Redis: {e}")
    redis_client = None


@app.post("/call_model")
def call_model(request: dict, apikey: str = Header(None)):
    """
    Forward POST request to ollama service with TTL caching and API key authentication.
    
    Requires APIKEY header with a valid API key.
    
    Expects a request body compatible with ollama's API endpoint.
    Example: {"model": "llama2", "prompt": "Hello"}
    
    Responses are cached with configurable TTL in Redis.
    """
    # Verify API key
    if not apikey:
        raise HTTPException(
            status_code=401,
            detail="Missing APIKEY header"
        )
    
    if not authenticator.verify_api_key(apikey):
        raise HTTPException(
            status_code=403,
            detail="Invalid API key"
        )
    
    # Check cache first
    cache_key = None
    if redis_client:
        cache_key = get_cache_key(request)
        try:
            cached_response = redis_client.get(cache_key)
            if cached_response:
                return json.loads(cached_response)
        except Exception as e:
            print(f"Cache retrieval error: {e}")
    
    try:
        # Forward the request to ollama's generate endpoint
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json=request,
            timeout=300.0,  # 5 minutes timeout for long-running requests
        )
        response.raise_for_status()
        response_data = response.json()
        
        # Cache the response
        if redis_client and cache_key:
            try:
                redis_client.setex(
                    cache_key,
                    CACHE_TTL,
                    json.dumps(response_data)
                )
            except Exception as e:
                print(f"Cache storage error: {e}")
        
        return response_data
    
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=502,
            detail=f"Error communicating with ollama service: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@app.get("/health")
def health():
    """Health check endpoint."""
    print(f"Calling health check at {OLLAMA_URL}/api/tags")
    try:
        response = requests.get(
            f"{OLLAMA_URL}/api/tags",
            timeout=5.0
        )
        response.raise_for_status()
        return {"status": "healthy", "ollama": "connected"}
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Ollama service unavailable: {str(e)}"
        )


if __name__ == "__main__":

    uvicorn.run(app, host="0.0.0.0",
                port=SERVICE_PORT)
