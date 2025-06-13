# ------------------ FULL BACKEND: app.py ------------------

# Import required libraries and modules
from flask import Flask, request, jsonify, send_from_directory, render_template, session, redirect, url_for
from flask_cors import CORS  # For handling Cross-Origin Resource Sharing
from openai import OpenAI  # OpenAI client for AI-powered content generation
import mysql.connector  # MySQL database connector
from datetime import datetime  # For handling date and time operations
from werkzeug.utils import secure_filename  # For secure file handling
import os  # For operating system interface

# Initialize Flask application with static file configuration
app = Flask(__name__, static_url_path='', static_folder='.')
CORS(app)  # Enable CORS for all routes

# Configure file upload settings
UPLOAD_FOLDER = 'uploads'  # Directory to store uploaded files
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # Create uploads directory if it doesn't exist

# Initialize OpenAI client with OpenRouter API configuration
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",  # OpenRouter API endpoint
    api_key="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"  # API key
)

# Establish MySQL database connection
conn = mysql.connector.connect(
    host='localhost',     # Database host
    user='root',         # Database username
    password='123abc',   # Database password
    database='student_portal'  # Database name
)
cursor = conn.cursor(dictionary=True)  # Create cursor with dictionary format for easier data handling

# Route to serve the main index page
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# Route to serve the home page
@app.route('/home')
def home():
    return send_from_directory('.', 'home.html')

# Route to serve the lesson page
@app.route('/lesson')
def lesson():
    return send_from_directory('.', 'lesson.html')

# User registration endpoint
@app.route('/signup', methods=['POST'])
def signup():
    # Extract user data from JSON request
    data = request.get_json()
    name, email, password = data['name'], data['email'], data['password']

    # Check if user already exists with the given email
    cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
    if cursor.fetchone():
        return jsonify({'message': 'User already exists'}), 400

    # Insert new user into database
    cursor.execute("INSERT INTO users (name, email, password) VALUES (%s, %s, %s)", (name, email, password))
    conn.commit()  # Commit the transaction
    return jsonify({'message': 'Signup successful'}), 201

# User login endpoint
@app.route('/login', methods=['POST'])
def login():
    # Extract login credentials from JSON request
    data = request.get_json()
    email, password = data['email'], data['password']

    # Verify user credentials against database
    cursor.execute("SELECT * FROM users WHERE email=%s AND password=%s", (email, password))
    user = cursor.fetchone()

    # Return appropriate response based on authentication result
    return jsonify({'message': 'Login successful'} if user else {'message': 'Invalid credentials'}), 200 if user else 401

# LESSONS

# AI-powered lesson generation endpoint
@app.route('/generate_lesson', methods=['POST'])
def generate_lesson():
    # Extract topic and user email from request
    data = request.get_json()
    topic, email = data.get('topic'), data.get('email')

    # Validate required fields
    if not topic or not email:
        return jsonify({"error": "Topic and Email are required"}), 400

    try:
        # Get user ID from email
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404

        user_id = user['id']
        
        # Generate lesson content using OpenAI API
        response = client.chat.completions.create(
            model="openai/gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an educational assistant that generates only lessons (no quiz or assignment)."},
                {"role": "user", "content": f"Generate a lesson for the topic: {topic}"}
            ],
            max_tokens=700  # Limit response length
        )
        lesson_content = response.choices[0].message.content

        # Store generated lesson in database
        cursor.execute("INSERT INTO lessons (user_id, email, topic, content) VALUES (%s, %s, %s, %s)",
                       (user_id, email, topic, lesson_content))
        conn.commit()
        return jsonify({"content": lesson_content})

    except Exception as e:
        print(f"Error generating lesson: {e}")
        return jsonify({"error": "Something went wrong while generating the lesson."}), 500


#QUIZ
# Get scheduled quiz information
@app.route('/get_quiz_schedule', methods=['GET'])
def get_quiz_schedule():
    try:
        # Fetch quiz schedule grouped by lesson number
        cursor.execute("""
            SELECT lesson_number, MIN(scheduled_datetime) AS scheduled_datetime
            FROM class_quiz_questions
            GROUP BY lesson_number
            ORDER BY lesson_number ASC
        """)
        quizzes = cursor.fetchall()
        return jsonify(quizzes)
    except Exception as e:
        print(f"Error loading quiz schedule: {e}")
        return jsonify([]), 500

# Get quiz questions for a specific lesson
@app.route('/get_quiz_questions', methods=['POST'])
def get_quiz_questions():
    # Extract lesson number from request
    lesson_number = request.get_json().get('lesson_number')
    try:
        # Fetch all questions for the specified lesson
        cursor.execute("SELECT * FROM class_quiz_questions WHERE lesson_number = %s", (lesson_number,))
        questions = cursor.fetchall()
        return jsonify({"questions": questions if questions else []})
    except Exception as e:
        print(f"Error fetching quiz questions: {e}")
        return jsonify({"questions": []}), 500

# Submit and grade class quiz
@app.route('/submit_class_quiz', methods=['POST'])
def submit_class_quiz():
    data = request.get_json()
    print("Received data for quiz submission:", data)  # Debug line
    
    # Extract submission data
    answers = data.get("answers")
    email = data.get("email")
    lesson_number = data.get("lesson_number")
    
    # Validate required fields
    if not email or not lesson_number or not answers:
        return jsonify({"error": "Missing required fields"}), 400
    
    score = 0  # Initialize score counter

    try:
        # Calculate score by comparing answers with correct options
        for answer in answers:
            cursor.execute("SELECT correct_option FROM class_quiz_questions WHERE id = %s", (answer['id'],))
            result = cursor.fetchone()
            if result and result['correct_option'] == answer['selected']:
                score += 1

        # Get user ID from email
        cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
        user = cursor.fetchone() 
        if not user:
            return jsonify({"score": score, "error": "User not found"}), 400
        user_id = user['id']

        # Count total questions answered
        total_questions = len(answers)

        # Insert or update quiz submission record
        cursor.execute("""
            INSERT INTO quiz_submissions (user_id, lesson_number, quiz_title, score, total_questions)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE score=%s, total_questions=%s, submitted_at=NOW()
        """, (user_id, lesson_number, "Class Quiz", score, total_questions, score, total_questions))
        conn.commit()

        return jsonify({"score": score})
    except Exception as e:
        print(f"Error submitting quiz: {e}")
        return jsonify({"score": 0}), 500

# Generate practice quiz using AI
@app.route('/generate_practice_quiz', methods=['POST'])
def generate_practice_quiz():
    # Extract topic from request
    topic = request.get_json().get("topic")
    try:
        # Generate quiz questions using OpenAI API
        response = client.chat.completions.create(
            model="openai/gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a quiz generator. Create a 5-question MCQ quiz on the given topic. Each question should have 4 options (A, B, C, D) and a correct_option (A/B/C/D). Respond ONLY with a JSON array, no explanation, no markdown, no extra text. Example: [{\"question\": \"...\", \"option_a\": \"...\", \"option_b\": \"...\", \"option_c\": \"...\", \"option_d\": \"...\", \"correct_option\": \"A\"}, ...]"},
                {"role": "user", "content": f"Generate a practice quiz for topic: {topic}"}
            ],
            max_tokens=700
        )
        
        # Parse AI response as JSON
        import json
        try:
            quiz_data = json.loads(response.choices[0].message.content)
        except Exception as e:
            print("AI raw response:", response.choices[0].message.content)
            return jsonify({"quiz": []}), 500
        return jsonify({"quiz": quiz_data})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"quiz": []}), 500

#ASSIGNMENTS
# Get all scheduled assignments
@app.route('/get_scheduled_assignments', methods=['GET'])
def get_scheduled_assignments():
    try:
        # Fetch all assignments ordered by deadline
        cursor.execute("SELECT * FROM scheduled_assignments ORDER BY deadline ASC")
        return jsonify(cursor.fetchall())
    except Exception as e:
        print(f"Error: {e}")
        return jsonify([]), 500

# Serve assignment PDF files
@app.route('/get_assignment_pdf/<filename>')
def get_assignment_pdf(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Submit assignment file
@app.route('/submit_assignment', methods=['POST'])
def submit_assignment():
    # Extract form data
    assignment_id = request.form['assignment_id']
    user_email = request.form['user_email']
    file = request.files['file']
    
    # Secure the filename and save the file
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    # Record the submission in database
    cursor.execute("INSERT INTO assignment_submissions (assignment_id, user_email, uploaded_file) VALUES (%s, %s, %s)",
                   (assignment_id, user_email, filename))
    conn.commit()
    return jsonify({"message": "Assignment submitted successfully!"})

# Admin route for uploading assignments
@app.route('/admin/upload_assignment', methods=['GET', 'POST'])
def upload_assignment():
    if request.method == 'POST':
        # Extract assignment details from form
        lesson_number = request.form['lesson_number']
        title = request.form['title']
        description = request.form['description']
        deadline = request.form['deadline']
        pdf = request.files['pdf_file']

        # Validate and save PDF file
        if pdf and pdf.filename.endswith('.pdf'):
            filename = secure_filename(pdf.filename)
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            pdf.save(save_path)

            # Insert assignment details into database
            cursor.execute("""
                INSERT INTO scheduled_assignments (lesson_number, title, description, pdf_filename, deadline)
                VALUES (%s, %s, %s, %s, %s)
            """, (lesson_number, title, description, filename, deadline))
            conn.commit()

            return "Assignment uploaded successfully."
        else:
            return "Only PDF files are allowed."

    # Render upload form for GET requests
    return render_template('upload_assignment.html')

# Generate practice assignment using AI
@app.route('/generate_practice_assignment', methods=['POST'])
def generate_practice_assignment():
    # Extract topic from request
    topic = request.get_json().get("topic")
    try:
        # Generate assignment question using OpenAI API
        response = client.chat.completions.create(
            model="openai/gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an educational assistant who gives a short assignment question."},
                {"role": "user", "content": f"Give a practice assignment question for: {topic}"}
            ]
        )
        question = response.choices[0].message.content
        return jsonify({"question": question})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"question": "Error generating assignment"}), 500

# Evaluate practice assignment using AI
@app.route('/evaluate_practice_assignment', methods=['POST'])
def evaluate_practice_assignment():
    # Extract question and answer from request
    data = request.get_json()
    answer, question = data.get("answer"), data.get("question")
    try:
        # Get AI evaluation and feedback
        response = client.chat.completions.create(
            model="openai/gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an assignment evaluator. Give clear feedback."},
                {"role": "user", "content": f"Question: {question}\n\nStudent Answer: {answer}\n\nEvaluate and suggest improvements."}
            ]
        )
        feedback = response.choices[0].message.content
        return jsonify({"feedback": feedback})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"feedback": "Error evaluating answer"}), 500

#RECORDS
# Get user's lesson history
@app.route('/get_user_lessons', methods=['GET'])
def get_user_lessons():
    # Get email parameter from query string
    email = request.args.get('email')
    if not email:
        return jsonify([]), 400
    
    try:
        # Fetch all lessons for the user ordered by creation date
        cursor.execute("""
            SELECT topic, created_at 
            FROM lessons 
            WHERE email = %s 
            ORDER BY created_at DESC
        """, (email,))
        lessons = cursor.fetchall()
        return jsonify(lessons)
    except Exception as e:
        print(f"Error fetching user lessons: {e}")
        return jsonify([]), 500

# Get user's quiz results history
@app.route('/get_user_quiz_results', methods=['GET'])
def get_user_quiz_results():
    # Get email parameter from query string
    email = request.args.get('email')
    if not email:
        return jsonify([]), 400
    
    try:
        # First get user_id from email
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        if not user:
            return jsonify([])
        
        user_id = user['id']
        
        # Get quiz results from quiz_submissions table
        cursor.execute("""
            SELECT 
                qs.quiz_title as title,
                qs.lesson_number,
                qs.score,
                qs.total_questions,
                qs.submitted_at
            FROM quiz_submissions qs
            WHERE qs.user_id = %s
            ORDER BY qs.submitted_at DESC
        """, (user_id,))
        
        quizzes = cursor.fetchall()
        return jsonify(quizzes)
        
    except Exception as e:
        print(f"Error fetching quiz results: {e}")
        return jsonify([]), 500

# Get user's assignment submission history
@app.route('/get_user_assignments', methods=['GET'])
def get_user_assignments():
    # Get email parameter from query string
    email = request.args.get('email')
    if not email:
        return jsonify([]), 400
    
    try:
        # Fetch assignment submissions with details joined from scheduled_assignments
        cursor.execute("""
            SELECT 
                sa.title,
                sa.deadline,
                asub.uploaded_file,
                asub.submission_time
            FROM assignment_submissions asub
            JOIN scheduled_assignments sa ON sa.id = asub.assignment_id
            WHERE asub.user_email = %s
            ORDER BY asub.submission_time DESC
        """, (email,))
        assignments = cursor.fetchall()
        return jsonify(assignments)
    except Exception as e:
        print(f"Error fetching user assignments: {e}")
        return jsonify([]), 500

# Render user records page with all user activity
@app.route('/records')
def records():
    # Get email parameter from query string
    email = request.args.get('email')
    if not email:
        return "Email required", 400

    # Get user ID from email
    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    if not user:
        return "User not found", 404
    user_id = user['id']

    # Fetch user's lessons
    cursor.execute("SELECT topic, created_at FROM lessons WHERE user_id = %s", (user_id,))
    lessons = cursor.fetchall()

    # Fetch user's quiz submissions
    cursor.execute("SELECT lesson_number, quiz_title, score, submitted_at FROM quiz_submissions WHERE user_id = %s", (user_id,))
    quizzes = cursor.fetchall()

    # Fetch user's assignment submissions with details
    cursor.execute("""
        SELECT s.title, s.deadline, a.uploaded_file, a.submitted_at 
        FROM scheduled_assignments s
        JOIN assignment_submissions a ON s.id = a.assignment_id 
        WHERE a.user_email = %s
    """, (email,))
    assignments = cursor.fetchall()

    # Render records template with user data
    return render_template("records.html", lessons=lessons, quizzes=quizzes, assignments=assignments)

# Run the Flask application in debug mode
if __name__ == '__main__':
    app.run(debug=True)