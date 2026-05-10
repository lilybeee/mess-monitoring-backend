from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import models, database
from pydantic import BaseModel, Field
import datetime
import asyncio
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with your frontend URL in production e.g. ["https://your-app.vercel.app"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# In-memory override state (admin can override day_type and menu description)
active_state = {
    "day_type": None,
    "menu_description": None
}


# ─────────────────────────────────────────────
# MEAL TIME WINDOWS
# ─────────────────────────────────────────────

MEAL_TIME_WINDOWS = {
    "breakfast": (datetime.time(7, 30), datetime.time(10, 0)),
    "lunch":     (datetime.time(12, 0), datetime.time(14, 30)),
    "snacks":    (datetime.time(16, 30), datetime.time(18, 0)),
    "dinner":    (datetime.time(19, 0), datetime.time(21, 0)),
}


# ─────────────────────────────────────────────
# PYDANTIC SCHEMAS
# ─────────────────────────────────────────────

class UpdateStatusRequest(BaseModel):
    day_status: str
    menu: str

class LoginRequest(BaseModel):
    username: str
    password: str

class UpdateMenuIdRequest(BaseModel):
    meal_type: str          # "breakfast" | "lunch" | "snacks" | "dinner"
    date: str               # "YYYY-MM-DD"
    menu_id: int = Field(..., ge=1, le=56)


# ─────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────

@app.get("/")
def health_check():
    return {"status": "Mess System Online", "database": "Connected to Neon"}


# ─────────────────────────────────────────────
# RASPBERRY PI INGEST (already deployed, keep intact)
# ─────────────────────────────────────────────

@app.post("/ingest")
def ingest_data(
    count: int,
    menu_id: int,
    day_type_id: int,
    db: Session = Depends(get_db)
):
    try:
        new_history = models.PeopleCount(
            menu_id=menu_id,
            people_total=count,
            day_type_id=day_type_id,
            timing=datetime.datetime.utcnow()
        )

        live_entry = db.query(models.LiveCount).first()
        if live_entry:
            live_entry.current_total = count
            live_entry.menu_id = menu_id
            live_entry.last_updated = datetime.datetime.utcnow()
        else:
            live_entry = models.LiveCount(menu_id=menu_id, current_total=count)
            db.add(live_entry)

        db.add(new_history)
        db.commit()
        return {"status": "success", "count_received": count}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

@app.post("/api/admin/login")
def login_admin(req: LoginRequest, db: Session = Depends(get_db)):
    admin = db.query(models.Admins).filter(models.Admins.name == req.username).first()
    if not admin or admin.password_hash != req.password or admin.role_id != 2:
        raise HTTPException(status_code=401, detail="Invalid credentials or insufficient permissions")
    return {"status": "success", "message": "Login successful"}


# ─────────────────────────────────────────────
# HELPER: build dashboard payload (shared by REST + SSE)
# ─────────────────────────────────────────────

def _build_dashboard(db: Session) -> dict:
    live_entry = db.query(models.LiveCount).first()
    current_people = live_entry.current_total if live_entry else 0
    menu_id = live_entry.menu_id if live_entry else None

    menu_desc = "Not Available"
    meal_type_name = "Not Available"

    if menu_id:
        menu = db.query(models.Menu).filter(models.Menu.menu_id == menu_id).first()
        if menu:
            menu_desc = menu.description
            meal_type = db.query(models.MealType).filter(
                models.MealType.meal_id == menu.meal_id
            ).first()
            if meal_type:
                meal_type_name = meal_type.meal_name

    day_status_name = "Normal Day"
    latest_pc = db.query(models.PeopleCount).order_by(
        models.PeopleCount.timing.desc()
    ).first()
    if latest_pc:
        day_type = db.query(models.DayType).filter(
            models.DayType.day_type_id == latest_pc.day_type_id
        ).first()
        if day_type:
            day_status_name = day_type.day_type_name

    # Apply admin overrides
    if active_state["day_type"]:
        day_status_name = active_state["day_type"]
    if active_state["menu_description"]:
        menu_desc = active_state["menu_description"]

    return {
        "currentPeople": current_people,
        "mealType": meal_type_name,
        "dayStatus": day_status_name,
        "menu": menu_desc,
        "lastUpdated": live_entry.last_updated.isoformat() if live_entry and live_entry.last_updated else None,
    }


# ─────────────────────────────────────────────
# STUDENT DASHBOARD — REST fallback
# ─────────────────────────────────────────────

@app.get("/api/student/dashboard")
def get_student_dashboard(db: Session = Depends(get_db)):
    try:
        return _build_dashboard(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# SSE — real-time live count stream
# Frontend connects once; server pushes every 3 seconds
# ─────────────────────────────────────────────

@app.get("/api/live-stream")
async def live_stream():
    async def event_generator():
        while True:
            db = database.SessionLocal()
            try:
                data = _build_dashboard(db)
                yield f"data: {json.dumps(data)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            finally:
                db.close()
            await asyncio.sleep(3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # prevents Railway/Nginx from buffering SSE
        },
    )


# ─────────────────────────────────────────────
# TRAFFIC HISTORY — for the Live Mess Traffic graph
# Returns all people_count rows for the current active menu
# ─────────────────────────────────────────────

@app.get("/api/student/traffic")
def get_traffic(db: Session = Depends(get_db)):
    try:
        live_entry = db.query(models.LiveCount).first()
        if not live_entry or not live_entry.menu_id:
            return {"traffic": []}

        records = (
            db.query(models.PeopleCount)
            .filter(models.PeopleCount.menu_id == live_entry.menu_id)
            .order_by(models.PeopleCount.timing.asc())
            .all()
        )

        traffic = [
            {
                "time": r.timing.strftime("%H:%M"),
                "people": r.people_total,
            }
            for r in records
        ]
        return {"traffic": traffic}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# ADMIN ENDPOINTS
# ─────────────────────────────────────────────

@app.get("/api/admin/dashboard")
def get_admin_dashboard(db: Session = Depends(get_db)):
    try:
        return _build_dashboard(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/day_types")
def get_day_types(db: Session = Depends(get_db)):
    day_types = db.query(models.DayType).all()
    if not day_types:
        return [
            {"id": 1, "name": "Normal Day"},
            {"id": 2, "name": "Exam Day"},
            {"id": 3, "name": "Feast"},
            {"id": 4, "name": "Holiday"},
            {"id": 5, "name": "Festival"},
        ]
    return [{"id": dt.day_type_id, "name": dt.day_type_name} for dt in day_types]


@app.post("/api/admin/update_status")
def update_status(req: UpdateStatusRequest, db: Session = Depends(get_db)):
    active_state["day_type"] = req.day_status
    active_state["menu_description"] = req.menu

    live_entry = db.query(models.LiveCount).first()
    if live_entry and live_entry.menu_id:
        # FIX: use bulk update to guarantee the write hits the DB
        db.query(models.Menu).filter(
            models.Menu.menu_id == live_entry.menu_id
        ).update({"description": req.menu}, synchronize_session=False)
        db.commit()

    return {"status": "success", "message": "State updated"}


# ─────────────────────────────────────────────
# ADMIN — UPDATE MENU ID FOR A DATE + MEAL WINDOW
# Updates all people_count rows that fall within the
# given meal's time window on the specified date.
# ─────────────────────────────────────────────

@app.patch("/api/admin/update_menu_id")
def update_menu_id(req: UpdateMenuIdRequest, db: Session = Depends(get_db)):
    meal_key = req.meal_type.lower()
    if meal_key not in MEAL_TIME_WINDOWS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid meal_type '{req.meal_type}'. Must be one of: {list(MEAL_TIME_WINDOWS.keys())}"
        )

    try:
        target_date = datetime.date.fromisoformat(req.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    start_time, end_time = MEAL_TIME_WINDOWS[meal_key]
    window_start = datetime.datetime.combine(target_date, start_time)
    window_end   = datetime.datetime.combine(target_date, end_time)

    # Verify menu_id exists in the menu table
    menu_exists = db.query(models.Menu).filter(models.Menu.menu_id == req.menu_id).first()
    if not menu_exists:
        raise HTTPException(status_code=404, detail=f"menu_id {req.menu_id} does not exist in the menu table.")

    # FIX: use bulk UPDATE instead of fetch-and-mutate loop
    # This bypasses the autoflush=False session setting and writes directly to the DB
    updated_count = (
        db.query(models.PeopleCount)
        .filter(
            models.PeopleCount.timing >= window_start,
            models.PeopleCount.timing <= window_end,
        )
        .update({"menu_id": req.menu_id}, synchronize_session=False)
    )

    if updated_count == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No records found for {req.meal_type} on {req.date} ({window_start.strftime('%H:%M')}–{window_end.strftime('%H:%M')})."
        )

    db.commit()

    return {
        "status": "success",
        "message": f"Updated {updated_count} record(s) for {req.meal_type} on {req.date} to menu_id {req.menu_id}.",
        "updated_rows": updated_count,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
    }


import os
import uvicorn

port = int(os.environ.get("PORT", 8000))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=port)
