from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Date
from database import Base
import datetime

class Role(Base):
    __tablename__ = "role"
    role_id = Column(Integer, primary_key=True)
    role_name = Column(String(50))

class Admins(Base):
    __tablename__ = "admins"
    user_id = Column(Integer, primary_key=True)
    name = Column(String(100))
    email = Column(String(100), unique=True)
    password_hash = Column(String(255))
    role_id = Column(Integer, ForeignKey("role.role_id"))

class DayType(Base):
    __tablename__ = "day_type"
    day_type_id = Column(Integer, primary_key=True)
    day_type_name = Column(String(50))

class MealType(Base):
    __tablename__ = "meal_type"
    meal_id = Column(Integer, primary_key=True)
    meal_name = Column(String(20))

class Menu(Base):
    __tablename__ = "menu"
    menu_id = Column(Integer, primary_key=True)
    week_no = Column(Integer)
    day_of_week = Column(Integer)
    meal_id = Column(Integer, ForeignKey("meal_type.meal_id"))
    description = Column(String)

class PeopleCount(Base):
    __tablename__ = "people_count"
    count_id = Column(Integer, primary_key=True)
    menu_id = Column(Integer, ForeignKey("menu.menu_id"))
    timing = Column(DateTime, default=datetime.datetime.utcnow) 
    people_total = Column(Integer)
    day_type_id = Column(Integer, ForeignKey("day_type.day_type_id"))

class LiveCount(Base):
    __tablename__ = "live_count"
    live_id = Column(Integer, primary_key=True)
    menu_id = Column(Integer, ForeignKey("menu.menu_id"))
    current_total = Column(Integer)
    last_updated = Column(DateTime, default=datetime.datetime.utcnow)
