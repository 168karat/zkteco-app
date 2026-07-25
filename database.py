from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean, UniqueConstraint, event
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

DATABASE_URL = "sqlite:///./zkteco.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Employee(Base):
    __tablename__ = "employees"
    
    id = Column(Integer, primary_key=True, index=True)
    pin = Column(String, unique=True, index=True) # ID that device uses
    name = Column(String, index=True)
    department = Column(String, default="General")
    role = Column(String, default="user") # 'admin' or 'user'
    password = Column(String, nullable=True) # Web dashboard password
    avatar_url = Column(String, nullable=True) # Profile picture path
    
    attendances = relationship("Attendance", back_populates="employee", cascade="all, delete-orphan")

class Attendance(Base):
    __tablename__ = "attendances"
    __table_args__ = (
        UniqueConstraint("employee_pin", "timestamp", name="uix_pin_time"),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    employee_pin = Column(String, ForeignKey("employees.pin"))
    timestamp = Column(DateTime, index=True)
    verify_mode = Column(Integer, default=0) # 0: password, 1: fingerprint, 15: face, etc.
    in_out_state = Column(Integer, default=0) # 0: Check-In, 1: Check-Out, etc.
    
    employee = relationship("Employee", back_populates="attendances")

class Device(Base):
    __tablename__ = "devices"
    
    id = Column(Integer, primary_key=True, index=True)
    sn = Column(String, unique=True, index=True)
    last_active = Column(DateTime, default=datetime.utcnow)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

Base.metadata.create_all(bind=engine)

# Auto Migration Check for avatar_url
try:
    with engine.connect() as conn:
        from sqlalchemy import text
        conn.execute(text("ALTER TABLE employees ADD COLUMN avatar_url VARCHAR;"))
        conn.commit()
except Exception:
    pass
