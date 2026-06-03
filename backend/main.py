import json
import os
import datetime
import secrets
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

# Importaciones locales unificadas con la estructura de directorios del backend
from backend.services.llm_service import generate_recipe_from_llm
from . import models
from . import auth
from . import email_utils
from .database import engine, SessionLocal

# Crear tablas en la base de datos automáticamente al inicializar
models.Base.metadata.create_all(bind=engine)

app = FastAPI()

# Configuración de CORS fluida
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir frontend estático de forma segura si la ruta existe
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

@app.get("/")
def root():
    return RedirectResponse(url="/static/login.html")

# Dependencia del ciclo de vida de la Base de Datos
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Función auxiliar para inyectar y verificar el usuario autenticado actual desde la BD
def get_current_user(email: str = Depends(auth.verify_token), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no autenticado o no encontrado.")
    return user


# ==========================================
# Controlador Global de Errores para la IA
# ==========================================
@app.exception_handler(HTTPException)
def custom_http_exception_handler(request, exc):
    """
    Captura de forma limpia los errores controlados (como los de OpenRouter)
    para devolver respuestas estructuradas legibles al frontend.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


# ==========================================
# Esquemas de Validación (Pydantic)
# ==========================================

class StudentCreate(BaseModel):
    name: str
    age: int
    grade: float

class StudentResponse(BaseModel):
    id: int
    name: str
    age: int
    grade: float

    class Config:
        from_attributes = True

class UserCreate(BaseModel):
    email: EmailStr

class UserResponse(BaseModel):
    id: int
    email: EmailStr
    is_active: bool

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class OTPRequest(BaseModel):
    email: EmailStr

class OTPVerify(BaseModel):
    email: EmailStr
    otp_code: str

# --- Esquemas de Ingredientes ---
class IngredientCreate(BaseModel):
    name: str
    quantity: str

class IngredientUpdate(BaseModel):
    quantity: str

class UserIngredientResponse(BaseModel):
    id: int
    ingredient_name: str
    quantity: str

    class Config:
        from_attributes = True

# --- Esquemas de Recetas ---
class RecipeResponse(BaseModel):
    id: int
    nombre_plato: str
    ingredientes: list[str]
    pasos: list[str]
    tiempo_estimado: str
    nivel_dificultad: str
    rating: int | None
    created_at: datetime.datetime

    class Config:
        from_attributes = True

class RateRecipeRequest(BaseModel):
    rating: int


# ==========================================
# Autenticación OTP
# ==========================================

@app.post("/auth/request-otp")
def request_otp(request: OTPRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == request.email).first()
    if not user:
        user = models.User(email=request.email)
        db.add(user)
        db.commit()
        db.refresh(user)

    otp_code = "".join([str(secrets.choice(range(10))) for _ in range(6)])
    
    user.otp_code = otp_code
    user.otp_created_at = datetime.datetime.utcnow()
    db.commit()

    email_sent = email_utils.send_otp_email(to_email=user.email, otp_code=otp_code)
    
    if not email_sent:
        raise HTTPException(status_code=500, detail="Error al enviar el correo. Verifica las credenciales SMTP.")

    return {"message": "Código OTP enviado exitosamente al correo."}


@app.post("/auth/verify-otp", response_model=Token)
def verify_otp(data: OTPVerify, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == data.email).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
        
    if not user.otp_code or user.otp_code != data.otp_code:
        raise HTTPException(status_code=400, detail="Código OTP incorrecto.")
        
    if not user.otp_created_at:
        raise HTTPException(status_code=400, detail="El código OTP no es válido.")
        
    expiration_time = user.otp_created_at + datetime.timedelta(minutes=10)
    if datetime.datetime.utcnow() > expiration_time:
        raise HTTPException(status_code=400, detail="El código OTP ha expirado. Solicita uno nuevo.")

    user.otp_code = None
    user.otp_created_at = None
    db.commit()
    
    access_token = auth.create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/users/me", response_model=UserResponse)
def read_users_me(current_user: models.User = Depends(get_current_user)):
    return current_user


# ==========================================
# CRUD Inventario de Ingredientes Personales
# ==========================================

@app.post("/ingredients", response_model=UserIngredientResponse)
def add_ingredient(
    ingredient_data: IngredientCreate, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    ing_name = ingredient_data.name.strip().lower()

    db_ingredient = db.query(models.Ingredient).filter(models.Ingredient.name == ing_name).first()
    if not db_ingredient:
        db_ingredient = models.Ingredient(name=ing_name)
        db.add(db_ingredient)
        db.commit()
        db.refresh(db_ingredient)

    user_ing = db.query(models.UserIngredient).filter(
        models.UserIngredient.user_id == current_user.id,
        models.UserIngredient.ingredient_id == db_ingredient.id
    ).first()

    if user_ing:
        user_ing.quantity = ingredient_data.quantity
    else:
        user_ing = models.UserIngredient(
            user_id=current_user.id,
            ingredient_id=db_ingredient.id,
            quantity=ingredient_data.quantity
        )
        db.add(user_ing)

    db.commit()
    db.refresh(user_ing)

    return UserIngredientResponse(
        id=user_ing.id,
        ingredient_name=db_ingredient.name,
        quantity=user_ing.quantity
    )


@app.get("/ingredients", response_model=list[UserIngredientResponse])
def get_user_ingredients(
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    items = db.query(models.UserIngredient).filter(
        models.UserIngredient.user_id == current_user.id
    ).all()
    
    result = []
    for item in items:
        result.append(
            UserIngredientResponse(
                id=item.id,
                ingredient_name=item.ingredient.name,
                quantity=item.quantity
            )
        )
    return result


@app.put("/ingredients/{id}", response_model=UserIngredientResponse)
def update_user_ingredient(
    id: int,
    ingredient_data: IngredientUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    user_ing = db.query(models.UserIngredient).filter(
        models.UserIngredient.id == id,
        models.UserIngredient.user_id == current_user.id
    ).first()

    if not user_ing:
        raise HTTPException(status_code=404, detail="Ingrediente no encontrado en tu inventario.")

    user_ing.quantity = ingredient_data.quantity
    db.commit()
    db.refresh(user_ing)

    return UserIngredientResponse(
        id=user_ing.id,
        ingredient_name=user_ing.ingredient.name,
        quantity=user_ing.quantity
    )


@app.delete("/ingredients/{id}")
def delete_user_ingredient(
    id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    user_ing = db.query(models.UserIngredient).filter(
        models.UserIngredient.id == id,
        models.UserIngredient.user_id == current_user.id
    ).first()

    if not user_ing:
        raise HTTPException(status_code=404, detail="Ingrediente no encontrado en tu inventario.")

    db.delete(user_ing)
    db.commit()

    return {"message": "Ingrediente eliminado de tu inventario correctamente."}


# ==========================================
# Gestión de Recetas e Integración con IA
# ==========================================

@app.post("/recipes/generate", response_model=RecipeResponse)
def generate_recipe(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    user_ingredients = db.query(models.UserIngredient).filter(
        models.UserIngredient.user_id == current_user.id
    ).all()

    if not user_ingredients:
        raise HTTPException(
            status_code=400,
            detail="Tu inventario está vacío. Agrega ingredientes antes de intentar generar una receta con la IA."
        )

    ingredients_list = [item.ingredient.name for item in user_ingredients]

    # Llamado seguro a la capa del servicio LLM
    recipe_data = generate_recipe_from_llm(ingredients_list=ingredients_list)

    new_recipe = models.Recipe(
        user_id=current_user.id,
        nombre_plato=recipe_data["nombre_plato"],
        ingredientes=json.dumps(recipe_data["ingredientes"]),
        pasos=json.dumps(recipe_data["pasos"]),
        tiempo_estimado=recipe_data["tiempo_estimado"],
        nivel_dificultad=recipe_data["nivel_dificultad"],
        rating=None
    )

    db.add(new_recipe)
    db.commit()
    db.refresh(new_recipe)

    return RecipeResponse(
        id=new_recipe.id,
        nombre_plato=new_recipe.nombre_plato,
        ingredientes=recipe_data["ingredientes"],
        pasos=recipe_data["pasos"],
        tiempo_estimado=new_recipe.tiempo_estimado,
        nivel_dificultad=new_recipe.nivel_dificultad,
        rating=new_recipe.rating,
        created_at=new_recipe.created_at
    )


@app.get("/recipes", response_model=list[RecipeResponse])
def get_user_recipes(
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    db_recipes = db.query(models.Recipe).filter(models.Recipe.user_id == current_user.id).all()
    
    recipes_list = []
    for r in db_recipes:
        recipes_list.append(
            RecipeResponse(
                id=r.id,
                nombre_plato=r.nombre_plato,
                ingredientes=json.loads(r.ingredientes),
                pasos=json.loads(r.pasos),
                tiempo_estimado=r.tiempo_estimado,
                nivel_dificultad=r.nivel_dificultad,
                rating=r.rating,
                created_at=r.created_at
            )
        )
    return recipes_list


@app.delete("/recipes/{id}")
def delete_recipe(
    id: int, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    recipe = db.query(models.Recipe).filter(
        models.Recipe.id == id, 
        models.Recipe.user_id == current_user.id
    ).first()

    if not recipe:
        raise HTTPException(status_code=404, detail="Receta no encontrada o no pertenece a tu historial.")

    db.delete(recipe)
    db.commit()
    return {"message": "Receta eliminada del historial correctamente."}


@app.post("/recipes/{id}/rate")
def rate_recipe(
    id: int,
    rate_data: RateRecipeRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if rate_data.rating < 1 or rate_data.rating > 5:
        raise HTTPException(status_code=400, detail="La calificación debe estar estrictamente entre 1 y 5 estrellas.")

    recipe = db.query(models.Recipe).filter(
        models.Recipe.id == id,
        models.Recipe.user_id == current_user.id
    ).first()

    if not recipe:
        raise HTTPException(status_code=404, detail="Receta no encontrada en tu historial.")

    recipe.rating = rate_data.rating
    db.commit()

    return {"message": f"Receta calificada con {rate_data.rating} estrellas correctamente."}


# ==========================================
# CRUD Estudiantes (Respetando Lógica del Repositorio)
# ==========================================

urls_sin_autenticacion = ["/static/login.html"]

@app.get("/students", response_model=list[StudentResponse])
def get_students(db: Session = Depends(get_db), email: str = Depends(auth.verify_token)):
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    students = db.query(models.Student).all()
    return students


@app.post("/students", response_model=StudentResponse)
def create_student(student: StudentCreate, db: Session = Depends(get_db), email: str = Depends(auth.verify_token)):
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    if student.age < 0:
        raise HTTPException(status_code=400, detail="La edad debe ser un número positivo.")
    
    if student.grade < 0.0 or student.grade > 5.0:
        raise HTTPException(status_code=400, detail="La calificación debe estar entre 0.0 y 5.0.")

    new_student = models.Student(
        name=student.name,
        age=student.age,
        grade=student.grade
    )
    db.add(new_student)
    db.commit()
    db.refresh(new_student)
    return new_student


@app.put("/students/{student_id}", response_model=StudentResponse)
def update_student(student_id: int, student: StudentCreate, db: Session = Depends(get_db), email: str = Depends(auth.verify_token)):
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")

    db_student = db.query(models.Student).filter(models.Student.id == student_id).first()

    if not db_student:
        raise HTTPException(status_code=404, detail="Student not found")

    db_student.name = student.name
    db_student.age = student.age
    db_student.grade = student.grade

    db.commit()
    db.refresh(db_student)
    return db_student


@app.delete("/students/{student_id}")
def delete_student(student_id: int, db: Session = Depends(get_db), email: str = Depends(auth.verify_token)):
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")

    db_student = db.query(models.Student).filter(models.Student.id == student_id).first()

    if not db_student:
        raise HTTPException(status_code=404, detail="Student not found")

    db.delete(db_student)
    db.commit()

    return {"message": "Student deleted successfully"}