from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext

import json
import os
from typing import List, Optional

# ---------------- CONFIG ----------------
SECRET_KEY = "83daa0256a2289b0fb23693bf1f6034d44396675749244721a2b20e896e11662"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

DB_FILE = "todos.json"
USERS_DB = {
    # default user in plain password form — verrà sostituito con hashed_password all'avvio
    "tim": {
        "username": "tim",
        "full_name": "Tim Ruscica",
        "email": "tim@gmail.com",
        "password": "secret",   # password di test: secret
        "disabled": False
    }
}

# ---------------- APP ----------------
app = FastAPI(title="Todo App (JSON) - JWT protected")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # in sviluppo ok, in produzione specifica il dominio
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- MODELS ----------------
class TodoCreate(BaseModel):
    title: str

class Todo(BaseModel):
    id: int
    title: str
    completed: bool = False

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class User(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: Optional[bool] = None

class UserInDB(User):
    hashed_password: str

# ---------------- AUTH UTILS ----------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def get_user(db, username: str):
    if username in db:
        user_data = db[username]
        return UserInDB(**user_data)
    return None

def authenticate_user(db, username: str, password: str):
    user = get_user(db, username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception

    user = get_user(USERS_DB, token_data.username)
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(current_user: UserInDB = Depends(get_current_user)):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

# ---------------- JSON DB HELPERS ----------------
def load_db() -> List[dict]:
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_db(todos: List[dict]):
    # write atomically
    tmp = DB_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB_FILE)

def next_id(todos: List[dict]) -> int:
    return max((t.get("id", 0) for t in todos), default=0) + 1

# ---------------- STARTUP: hash user password if plain provided ----------------
@app.on_event("startup")
def startup_event():
    global USERS_DB
    for uname, data in list(USERS_DB.items()):
        # if there's a 'password' plaintext field, replace with hashed_password
        if "password" in data:
            pw = data.pop("password")
            data["hashed_password"] = get_password_hash(pw)
            USERS_DB[uname] = data

# ---------------- TODO ROUTES (PROTECTED) ----------------
@app.get("/todos", response_model=List[Todo])
def get_todos(current_user: User = Depends(get_current_active_user)):
    return load_db()

@app.post("/todos", response_model=Todo, status_code=201)
def create_todo(item: TodoCreate, current_user: User = Depends(get_current_active_user)):
    if not item.title or item.title.strip() == "":
        raise HTTPException(status_code=400, detail="Missing title")

    todos = load_db()
    new_id = next_id(todos)
    todo = {"id": new_id, "title": item.title.strip(), "completed": False}
    todos.append(todo)
    save_db(todos)
    return todo

@app.delete("/todos/{todo_id}")
def delete_todo(todo_id: int, current_user: User = Depends(get_current_active_user)):
    todos = load_db()
    new_list = [t for t in todos if t["id"] != todo_id]
    if len(new_list) == len(todos):
        raise HTTPException(status_code=404, detail="Todo not found")
    save_db(new_list)
    return {"message": "deleted"}

@app.put("/todos/{todo_id}", response_model=Todo)
def update_todo(todo_id: int, body: dict, current_user: User = Depends(get_current_active_user)):
    todos = load_db()
    todo = next((t for t in todos if t["id"] == todo_id), None)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    if "title" in body:
        todo["title"] = body["title"]
    if "completed" in body:
        todo["completed"] = bool(body["completed"])
    save_db(todos)
    return todo

# ---------------- AUTH ROUTES ----------------
@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(USERS_DB, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username}, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me/", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user
