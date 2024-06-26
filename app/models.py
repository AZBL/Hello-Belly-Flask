from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app import db


class User(db.Model):
    id = db.Column(db.String(255), primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)  # Add the name field
    appointments = db.relationship('Appointment', backref='user', lazy=True)

class Doctor(db.Model):
    id = Column(String(255), primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    appointments = relationship('Appointment', backref='doctor', lazy=True)
    time_slots = relationship('TimeSlot', backref='doctor', lazy=True)
class TimeSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.String(255), db.ForeignKey('doctor.id'), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    is_available = db.Column(db.Boolean, default=True)
    appointment_id = db.Column(db.String(255), db.ForeignKey('appointment.id'), nullable=True)
class Appointment(db.Model):
    id = db.Column(db.String(255), primary_key=True)
    date = db.Column(db.DateTime, nullable=False)
    purpose = db.Column(db.String(255), nullable=False)
    doctor_id = db.Column(db.String(255), db.ForeignKey('doctor.id'), nullable=False)
    user_id = db.Column(db.String(255), db.ForeignKey('user.id'), nullable=False)
    meeting_url = db.Column(db.String(255), nullable=False)
    moderator_url = db.Column(db.String(255), nullable=False)
    meeting_password = db.Column(db.String(255), nullable=False)

    def to_dict(self):
        user = User.query.get(self.user_id)
        doctor = Doctor.query.get(self.doctor_id)
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'purpose': self.purpose,
            'doctor': {
                'id': doctor.id,
                'name': doctor.name,
                'email': doctor.email
            },
            'user': {
                'id': user.id,
                'name': user.name,  # Ensure name is included
                'email': user.email
            },
            'meeting_url': self.meeting_url,
            'moderator_url': self.moderator_url,
            'meeting_password': self.meeting_password,
        }