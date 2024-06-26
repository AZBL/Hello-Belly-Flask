import os
from flask import Blueprint, request, jsonify, redirect, make_response
from app import app, db
from app.models import User, Appointment, Doctor, TimeSlot
import logging, time, jwt, requests, base64, hashlib, hmac, random, string
from . import api
from datetime import datetime, timedelta
from flask_cors import cross_origin, CORS
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from pprint import pprint
from dotenv import load_dotenv
import pytz

load_dotenv()

logging.basicConfig(level=logging.DEBUG)

CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

DOCTOR_EMAIL = "TORCSH30@gmail.com"
appointments = []

CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI')
SECRET_TOKEN = os.getenv('SECRET_TOKEN')
AUTHORIZATION_BASE_URL = os.getenv('AUTHORIZATION_BASE_URL')
TOKEN_URL = os.getenv('TOKEN_URL')
API_BASE_URL = os.getenv('API_BASE_URL')
SENDINBLUE_API_KEY = os.getenv('SENDINBLUE_API_KEY')  # Your Sendinblue API key
########################################################################################



def generate_time_slots_for_year(doctor_id):
    slots = []
    current_date = datetime.now()
    end_date = current_date + timedelta(days=365)
    
    while current_date < end_date:
        start_time = datetime(current_date.year, current_date.month, current_date.day, 9, 0)
        end_time = datetime(current_date.year, current_date.month, current_date.day, 17, 0)
        
        while start_time < end_time:
            slots.append(TimeSlot(doctor_id=doctor_id, start_time=start_time))
            start_time += timedelta(minutes=30)
        
        current_date += timedelta(days=1)
    
    db.session.bulk_save_objects(slots)
    db.session.commit()

def generate_full_day_slots(date):
    """Generate all possible slots for a given date from 9:00 AM to 5:00 PM."""
    start_time = datetime.combine(date, datetime.min.time()) + timedelta(hours=9)
    end_time = datetime.combine(date, datetime.min.time()) + timedelta(hours=17)
    slots = []
    while start_time < end_time:
        slots.append(start_time)
        start_time += timedelta(minutes=30)
    return slots



def get_taken_slots(doctor_id, date):
    start_day = datetime.combine(date, datetime.min.time())
    end_day = start_day + timedelta(days=1)
    taken_slots = Appointment.query.filter(
        Appointment.doctor_id == doctor_id,
        Appointment.date >= start_day,
        Appointment.date < end_day
    ).all()
    return [appointment.date for appointment in taken_slots]

@api.route('/')
def home():
    app.logger.info('Home route accessed')
    return 'Welcome to the Zoom Integration'

def encode_credentials(client_id, client_secret):
    credentials = f"{client_id}:{client_secret}"
    base64_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    return base64_credentials

# Function to generate random strings
def generate_random_string(length=12):
    letters = string.ascii_letters + string.digits
    return ''.join(random.choice(letters) for i in range(length))

@app.route('/api/schedule_meeting', methods=['POST'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def schedule_meeting():
    data = request.json
    date_str = data.get('date')
    purpose = data.get('purpose')
    doctor_id = data.get('doctor')
    user_email = data.get('email')
    user_name = data.get('name')

    app.logger.debug(f"Received data: {data}")

    if not all([date_str, purpose, doctor_id, user_email, user_name]):
        app.logger.error('Missing data in schedule_meeting request')
        return jsonify({'error': 'Missing data'}), 400

    # Parse the date and subtract 4 hours
    date = datetime.fromisoformat(date_str) - timedelta(hours=4)
    app.logger.debug(f"Parsed date (adjusted): {date}")

    # Check if the slot is available
    existing_appointment = Appointment.query.filter_by(doctor_id=doctor_id, date=date).first()
    if existing_appointment:
        app.logger.error("Time slot is already booked")
        return jsonify({'error': 'Time slot is already booked'}), 400

    meeting_id = generate_random_string()
    meeting_password = generate_random_string(8)
    meeting_url = f"https://meet.jit.si/{meeting_id}"
    moderator_url = f"https://meet.jit.si/{meeting_id}#config.password={meeting_password}"

    subject = f"Meeting Scheduled: {purpose}"

    user = User.query.filter_by(email=user_email).first()
    if not user:
        user = User(id=generate_random_string(), email=user_email, name=user_name)
        db.session.add(user)
        db.session.commit()
    else:
        user.name = user_name  # Update the name if it already exists

    doctor = Doctor.query.filter_by(id=doctor_id).first()
    if not doctor:
        app.logger.error("Doctor not found")
        return jsonify({'error': 'Doctor not found'}), 404

    appointment = Appointment(
        id=meeting_id,
        date=date,
        purpose=purpose,
        doctor_id=doctor.id,
        user_id=user.id,
        meeting_url=meeting_url,
        moderator_url=moderator_url,
        meeting_password=meeting_password
    )
    db.session.add(appointment)
    db.session.commit()

    body = f"""
    Meeting Details:
    Purpose: {purpose}
    Date and Time: {date}
    Meeting URL: {meeting_url}
    
    Please join the meeting at the specified time.
    """

    moderator_body = f"""
    Meeting Details:
    Purpose: {purpose}
    Date and Time: {date}
    Meeting URL: {meeting_url}
    Moderator URL: {moderator_url}
    Meeting Password: {meeting_password}
    
    Please join the meeting at the specified time.
    """

    app.logger.info(f"Meeting scheduled successfully: {appointment.to_dict()}")

    send_email(doctor.email, subject, moderator_body)
    send_email(user_email, subject, body)

    return jsonify({'message': 'Meeting scheduled successfully', 'appointment': appointment.to_dict()})


@app.route('/api/appointments', methods=['GET'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def list_appointments():
    user_email = request.args.get('email')
    if not user_email:
        app.logger.error('Missing user email in request')
        return jsonify({'error': 'Missing user email'}), 400

    user = User.query.filter_by(email=user_email).first()
    if not user:
        app.logger.warning(f'User with email {user_email} not found')
        return jsonify({'appointments': []})

    appointments = Appointment.query.filter_by(user_id=user.id).all()
    app.logger.info(f"Appointments retrieved for user {user_email}: {[a.to_dict() for a in appointments]}")
    return jsonify({'appointments': [a.to_dict() for a in appointments]})

    appointments = Appointment.query.filter_by(user_id=user.id).all()
    app.logger.info(f"Appointments retrieved for user {user_email}: {[a.to_dict() for a in appointments]}")
    return jsonify({'appointments': [a.to_dict() for a in appointments]})

@app.route('/api/appointments', methods=['POST'])
@cross_origin()
def schedule_appointment():
    data = request.json
    doctor_id = data['doctor_id']
    user_id = data['user_id']
    date = datetime.fromisoformat(data['date'])
    purpose = data['purpose']
    meeting_url = data['meeting_url']
    moderator_url = data['moderator_url']
    meeting_password = data['meeting_password']

    # Find the corresponding time slot
    time_slot = TimeSlot.query.filter_by(doctor_id=doctor_id, start_time=date, is_available=True).first()
    
    if not time_slot:
        return jsonify({'error': 'Time slot is not available'}), 400

    # Create the appointment
    appointment = Appointment(
        id=data['id'],
        date=date,
        purpose=purpose,
        doctor_id=doctor_id,
        user_id=user_id,
        meeting_url=meeting_url,
        moderator_url=moderator_url,
        meeting_password=meeting_password
    )

    db.session.add(appointment)
    
    # Update the time slot to be unavailable
    time_slot.is_available = False
    time_slot.appointment_id = appointment.id
    
    db.session.commit()

    return jsonify(appointment.to_dict()), 201

@app.route('/api/appointments/<appointment_id>', methods=['DELETE'])
@cross_origin()
def cancel_appointment(appointment_id):
    appointment = Appointment.query.get(appointment_id)
    
    if not appointment:
        return jsonify({'error': 'Appointment not found'}), 404
    
    # Find the corresponding time slot and make it available
    time_slot = TimeSlot.query.filter_by(appointment_id=appointment_id).first()
    if time_slot:
        time_slot.is_available = True
        time_slot.appointment_id = None

    db.session.delete(appointment)
    db.session.commit()

    return jsonify({'message': 'Appointment canceled successfully'}), 200

@app.route('/api/appointments/<appointment_id>', methods=['PUT'])
@cross_origin()
def reschedule_appointment(appointment_id):
    data = request.json
    new_date = datetime.fromisoformat(data['date'])

    appointment = Appointment.query.get(appointment_id)
    
    if not appointment:
        return jsonify({'error': 'Appointment not found'}), 404
    
    # Find the new time slot
    new_time_slot = TimeSlot.query.filter_by(doctor_id=appointment.doctor_id, start_time=new_date, is_available=True).first()
    
    if not new_time_slot:
        return jsonify({'error': 'New time slot is not available'}), 400
    
    # Make the old time slot available
    old_time_slot = TimeSlot.query.filter_by(appointment_id=appointment_id).first()
    if old_time_slot:
        old_time_slot.is_available = True
        old_time_slot.appointment_id = None
    
    # Update the appointment
    appointment.date = new_date
    appointment.meeting_url = data['meeting_url']
    appointment.moderator_url = data['moderator_url']
    appointment.meeting_password = data['meeting_password']

    # Reserve the new time slot
    new_time_slot.is_available = False
    new_time_slot.appointment_id = appointment.id

    db.session.commit()

    return jsonify(appointment.to_dict()), 200


def send_email(to_email, subject, body):
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = SENDINBLUE_API_KEY
    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

    sender = {"email": "your-email@example.com", "name": "Your Name"}  # Replace with your verified Sendinblue sender email and name
    receivers = [{"email": to_email}]

    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=receivers,
        sender=sender,
        subject=subject,
        text_content=body
    )

    try:
        api_response = api_instance.send_transac_email(send_smtp_email)
        pprint(api_response)
    except ApiException as e:
        print(f"Failed to send email to {to_email}: {e}")

@app.route('/api/doctors', methods=['POST'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def create_doctor():
    data = request.json
    name = data.get('name')
    email = data.get('email')

    if not all([name, email]):
        app.logger.error('Missing data in request')
        return jsonify({'error': 'Missing data'}), 400

    doctor = Doctor(id=generate_random_string(), name=name, email=email)
    db.session.add(doctor)
    db.session.commit()

    # Generate time slots for the new doctor
    generate_time_slots_for_year(doctor.id)

    app.logger.info(f"Doctor created successfully: {doctor}")
    return jsonify({'message': 'Doctor created successfully', 'doctor': {'id': doctor.id, 'name': doctor.name, 'email': doctor.email}}), 201

@app.route('/api/admin/doctors', methods=['GET'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def admin_list_doctors():
    doctors = Doctor.query.all()
    app.logger.info(f"Doctors retrieved: {[doctor.name for doctor in doctors]}")
    return jsonify({'doctors': [{'id': doctor.id, 'name': doctor.name, 'email': doctor.email} for doctor in doctors]})

@app.route('/api/admin/doctors', methods=['POST'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def admin_create_doctor():
    data = request.json
    admin_email = request.args.get('admin_email')

    if admin_email != 'torcsh30@gmail.com':
        app.logger.error('Unauthorized access attempt')
        return jsonify({'error': 'Unauthorized access'}), 403

    name = data.get('name')
    email = data.get('email')

    if not all([name, email]):
        app.logger.error('Missing data in request')
        return jsonify({'error': 'Missing data'}), 400

    doctor = Doctor(id=generate_random_string(), name=name, email=email)
    db.session.add(doctor)
    db.session.commit()

    app.logger.info(f"Doctor created successfully: {doctor}")
    return jsonify({'message': 'Doctor created successfully', 'doctor': {'id': doctor.id, 'name': doctor.name, 'email': doctor.email}}), 201

@app.route('/api/doctors', methods=['GET'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def list_doctors():
    doctors = Doctor.query.all()
    app.logger.info(f"Doctors retrieved: {[doctor.name for doctor in doctors]}")
    return jsonify({'doctors': [{'id': doctor.id, 'name': doctor.name, 'email': doctor.email} for doctor in doctors]})

@app.route('/api/is_doctor', methods=['GET'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def is_doctor():
    user_email = request.args.get('email')
    if not user_email:
        app.logger.error('Missing user email in request')
        return jsonify({'error': 'Missing user email'}), 400

    doctor = Doctor.query.filter_by(email=user_email).first()
    is_doctor = doctor is not None

    app.logger.info(f"Checked if user is a doctor: {user_email}, is_doctor: {is_doctor}")
    return jsonify({'is_doctor': is_doctor})

@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def available_slots():
    doctor_id = request.args.get('doctor_id')
    date_str = request.args.get('date')

    # Parse the date without converting time zones
    date = datetime.strptime(date_str, "%Y-%m-%d")

    # Generate full day slots
    full_day_slots = generate_full_day_slots(date)

    # Get taken slots and adjust by subtracting 4 hours
    taken_slots = [slot.date for slot in get_taken_slots(doctor_id, date)]
    adjusted_taken_slots = [slot - timedelta(hours=4) for slot in taken_slots]

    # Remove taken slots from full day slots
    available_slots = [slot.isoformat() for slot in full_day_slots if slot not in adjusted_taken_slots]

    return jsonify({'available_slots': available_slots})

@app.route('/api/doctor_appointments', methods=['GET'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def doctor_appointments():
    doctor_id = request.args.get('doctor_id')
    app.logger.info(f"Received doctor_appointments request for doctor_id: {doctor_id}")
    if not doctor_id:
        app.logger.error("Missing doctor_id in doctor_appointments request")
        return jsonify({'error': 'Missing doctor_id'}), 400

    appointments = Appointment.query.filter_by(doctor_id=doctor_id).all()
    app.logger.info(f"Fetched appointments: {appointments}")
    return jsonify({'appointments': [appointment.to_dict() for appointment in appointments]})


@app.route('/api/doctor_by_email', methods=['GET'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def get_doctor_by_email():
    email = request.args.get('email')
    app.logger.info(f"Received get_doctor_by_email request for email: {email}")
    if not email:
        app.logger.error("Missing email in get_doctor_by_email request")
        return jsonify({'error': 'Missing email'}), 400

    doctor = Doctor.query.filter_by(email=email).first()
    if not doctor:
        app.logger.error("Doctor not found")
        return jsonify({'error': 'Doctor not found'}), 404

    app.logger.info(f"Fetched doctor: {doctor}")
    return jsonify({'id': doctor.id, 'name': doctor.name, 'email': doctor.email})



@app.route('/api/available_slots', methods=['GET'])
@cross_origin(origins='http://localhost:5173', supports_credentials=True)
def get_available_slots():
    doctor_id = request.args.get('doctor_id')
    date_str = request.args.get('date')

    if not all([doctor_id, date_str]):
        app.logger.error('Missing data in available_slots request')
        return jsonify({'error': 'Missing data'}), 400

    date = datetime.fromisoformat(date_str)
    start_time = date.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = date.replace(hour=17, minute=0, second=0, microsecond=0)
    all_slots = [start_time + timedelta(minutes=30 * i) for i in range(17)]

    taken_slots = Appointment.query.filter_by(doctor_id=doctor_id).filter(
        Appointment.date.between(start_time, end_time)
    ).all()

    taken_slots = [appointment.date for appointment in taken_slots]
    available_slots = [slot for slot in all_slots if slot not in taken_slots]

    app.logger.debug(f"Full Day Slots: {all_slots}")
    app.logger.debug(f"Taken Slots: {taken_slots}")
    app.logger.debug(f"Available Slots: {available_slots}")

    return jsonify({'available_slots': [slot.isoformat() for slot in available_slots]})

@app.route('/api/unavailable_slots', methods=['GET'])
def get_unavailable_slots():
    doctor_id = request.args.get('doctor_id')
    slots = UnavailableSlot.query.filter_by(doctor_id=doctor_id).all()
    app.logger.debug(f"Unavailable Slots: {slots}")
    return jsonify({'unavailable_slots': [slot.to_dict() for slot in slots]})

# New route to mark a slot as unavailable
@app.route('/api/unavailable_slots', methods=['POST'])
def mark_unavailable_slot():
    data = request.json
    doctor_id = data.get('doctor_id')
    date_str = data.get('date')
    date = datetime.fromisoformat(date_str)
    slot = UnavailableSlot(doctor_id=doctor_id, date=date)
    db.session.add(slot)
    db.session.commit()
    return jsonify({'slot': slot.to_dict()}), 201
