import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.routes import users
from app.routes import watchlist 
from app.routes import subscriptions
from app.routes import market

app = FastAPI(
    title="Fin-Station API",
    description="Backend for Fin-Station Financial Platform",
    version="1.0.0"
)

# --- 1. CORS Setup ---
# Abhi ke liye sabhi origins allow kar rahe hain, production mein ise apne frontend domain se replace kar dena
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # e.g., ["http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 2. Custom Middleware (Processing Time & Logging) ---
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    # Response headers mein time add kar diya (X-Process-Time)
    response.headers["X-Process-Time"] = str(process_time)
    print(f"[{request.method}] {request.url.path} - Completed in {process_time:.4f} secs")
    return response

# --- 3. Include Routers ---
app.include_router(users.router)
app.include_router(watchlist.router)
app.include_router(subscriptions.router)
app.include_router(market.router)

@app.get("/")
def read_root():
    return {"message": "Welcome to Fin-Station Backend! Server is running."}