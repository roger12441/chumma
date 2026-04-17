import os
import uuid
import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Float, JSON, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.dialects.postgresql import UUID
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path="files/.env")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:your_db_password@db.your-project-ref.supabase.co:5432/postgres?sslmode=require",
)

# Supabase requires SSL — ensure sslmode=require is always present
if "sslmode" not in DATABASE_URL:
    DATABASE_URL += "?sslmode=require"

engine = create_engine(DATABASE_URL, connect_args={"sslmode": "require"})
Base = declarative_base()

class InterviewSession(Base):
    __tablename__ = "interview_sessions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_name = Column(String(255), nullable=False)
    face_verified = Column(Boolean, default=False)
    origin_url = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    submitted = Column(Boolean, default=False)
    submitted_at = Column(DateTime, nullable=True)
    
    # Relationships
    profile = relationship("CandidateProfile", back_populates="session", uselist=False)
    questions = relationship("Question", back_populates="session")
    evaluations = relationship("AnswerEvaluation", back_populates="session")
    result = relationship("InterviewResult", back_populates="session", uselist=False)

class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("interview_sessions.id"), nullable=False, unique=True)
    skills = Column(Text, nullable=True)
    projects = Column(Text, nullable=True)
    experience = Column(Text, nullable=True)
    education = Column(Text, nullable=True)
    certifications = Column(Text, nullable=True)
    speech_transcript = Column(Text, nullable=True)
    additional_information = Column(JSON, nullable=True)
    
    session = relationship("InterviewSession", back_populates="profile")

class Question(Base):
    __tablename__ = "questions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("interview_sessions.id"), nullable=False)
    ordinal_number = Column(Integer, nullable=False)
    difficulty = Column(String(50), nullable=False) # 'easy', 'medium', 'hard'
    category = Column(String(50), nullable=False) # 'technical', 'project', 'behavioural', 'general'
    question_text = Column(Text, nullable=False)
    
    session = relationship("InterviewSession", back_populates="questions")
    ideal_answer = relationship("IdealAnswer", back_populates="question", uselist=False)
    evaluation = relationship("AnswerEvaluation", back_populates="question", uselist=False)

class IdealAnswer(Base):
    __tablename__ = "ideal_answers"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id"), nullable=False, unique=True)
    ideal_answer_text = Column(Text, nullable=False)
    
    question = relationship("Question", back_populates="ideal_answer")

class AnswerEvaluation(Base):
    __tablename__ = "answer_evaluations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("interview_sessions.id"), nullable=False)
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id"), nullable=False, unique=True)
    candidate_answer = Column(Text, nullable=True)
    score = Column(Integer, default=0)
    feedback = Column(Text, nullable=True)
    badge = Column(String(50), nullable=True) # 'Excellent', 'Good', etc.
    
    session = relationship("InterviewSession", back_populates="evaluations")
    question = relationship("Question", back_populates="evaluation")

class InterviewResult(Base):
    __tablename__ = "interview_results"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("interview_sessions.id"), nullable=False, unique=True)
    total_score = Column(Integer, default=0)
    max_score = Column(Integer, default=150)
    percentage = Column(Float, default=0.0)
    grade = Column(String(10), nullable=True)
    summary = Column(Text, nullable=True)
    
    session = relationship("InterviewSession", back_populates="result")

def migrate():
    print(f"Initializing migration with DATABASE_URL: {DATABASE_URL}")
    try:
        Base.metadata.create_all(engine)
        print("✅ Database schema created successfully.")
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        print("\nNote: Ensure you have the necessary database drivers installed (e.g., 'pip install psycopg2-binary' for PostgreSQL).")

if __name__ == "__main__":
    migrate()
