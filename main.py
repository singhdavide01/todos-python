from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json
import os

app = FastAPI()

DB_FILE = "todos.json"

# CORS per frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------- UTILS -----------------

def load_db():
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE, "r") as f:
        try:
            return json.load(f)
        except:
            return []


def save_db(todos):
    with open(DB_FILE, "w") as f:
        json.dump(todos, f)


# ----------------- API ROUTES -----------------

@app.get("/todos")
def get_todos():
    return load_db()


@app.post("/todos")
def create_todo(item: dict):
    if "title" not in item or item["title"].strip() == "":
        raise HTTPException(status_code=400, detail="Missing title")

    todos = load_db()
    new_id = max([t["id"] for t in todos], default=0) + 1

    todo = {
        "id": new_id,
        "title": item["title"],
        "completed": False
    }

    todos.append(todo)
    save_db(todos)

    return todo


@app.delete("/todos/{todo_id}")
def delete_todo(todo_id: int):
    todos = load_db()
    new_list = [t for t in todos if t["id"] != todo_id]

    if len(new_list) == len(todos):
        raise HTTPException(status_code=404, detail="Todo not found")

    save_db(new_list)
    return {"message": "deleted"}


@app.put("/todos/{todo_id}")
def update_todo(todo_id: int, body: dict):
    todos = load_db()
    todo = next((t for t in todos if t["id"] == todo_id), None)

    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    if "title" in body:
        todo["title"] = body["title"]
    if "completed" in body:
        todo["completed"] = body["completed"]

    save_db(todos)
    return todo
