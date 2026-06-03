import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    is_active = Column(Boolean, default=True)
    otp_code = Column(String, nullable=True)
    otp_created_at = Column(DateTime, nullable=True)

    # Relación uno a muchos: Un usuario puede tener muchos ingredientes en su inventario
    inventory = relationship("UserIngredient", back_populates="user", cascade="all, delete-orphan")
    
    # Relación uno a muchos: Un usuario puede tener muchas recetas en su historial
    recipes = relationship("Recipe", back_populates="user", cascade="all, delete-orphan")


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    grade = Column(Float, nullable=False)


class Ingredient(Base):
    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)  # Ejemplo: "pollo", "arroz"

    # Relación inversa para saber qué usuarios tienen este ingrediente (opcional, ayuda al ORM)
    user_associations = relationship("UserIngredient", back_populates="ingredient")


class UserIngredient(Base):
    """
    Tabla intermedia para el inventario de los usuarios.
    Relaciona un Usuario con un Ingrediente y le añade el atributo de cantidad de forma dinámica.
    """
    __tablename__ = "user_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=False)
    quantity = Column(String, nullable=True)  # Ejemplo: "500g", "3 unidades", "1 cucharada"

    # Relaciones de mapeo inverso hacia las tablas principales
    user = relationship("User", back_populates="inventory")
    ingredient = relationship("Ingredient", back_populates="user_associations")


class Recipe(Base):
    """
    Tabla para almacenar el historial de recetas generadas por la IA (OpenRouter).
    Los campos estructurados 'ingredientes' y 'pasos' se almacenan como texto plano en formato JSON.
    """
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Campos obligatorios del JSON de respuesta requeridos por el esquema de la IA
    nombre_plato = Column(String, nullable=False)
    ingredientes = Column(String, nullable=False)  # Se guardará estructurado como texto JSON (lista de ingredientes usados)
    pasos = Column(String, nullable=False)         # Se guardará estructurado como texto JSON (lista de instrucciones secuenciales)
    tiempo_estimado = Column(String, nullable=False)
    nivel_dificultad = Column(String, nullable=False)
    
    # Calificación opcional que el usuario puede darle a la receta (estricto de 1 a 5 estrellas)
    rating = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relación de mapeo inverso hacia el creador de la receta
    user = relationship("User", back_populates="recipes")