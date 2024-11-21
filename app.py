import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, VideoUnavailable
from deep_translator import GoogleTranslator
import google.generativeai as genai
from pymongo import MongoClient
from dotenv import load_dotenv
import os
import datetime
import bcrypt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# Load environment variables
load_dotenv()

# MongoDB connection setup
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    st.error("MongoDB URI is missing. Please set it in your .env file.")
else:
    try:
        # Attempt to establish a connection
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)  # Add a timeout for better error handling
        client.admin.command("ping")  # Verify connection to MongoDB Atlas
        db = client.youtube_app_db  # Replace with your database name
        users_collection = db.users  # Users collection
        content_collection = db.generated_content  # Content collection
    except Exception as e:
        st.error(f"Failed to connect to MongoDB Atlas: {e}")

# Admin credentials from .env
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# Configure Google Gemini API
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    st.error("Google API Key is missing. Please set it in your .env file.")
else:
    genai.configure(api_key=API_KEY)

# Function to fetch transcript
def fetch_transcript(video_id, language="en"):
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = transcript_list.find_transcript([language])
        return " ".join([entry['text'] for entry in transcript.fetch()])
    except NoTranscriptFound:
        st.error("Transcript not available for this video.")
    except VideoUnavailable:
        st.error("The video is unavailable. Please try another link.")
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
    return None

# Function to generate content
def generate_content(content_type, transcript_text, desired_word_count=None):
    try:
        model = genai.GenerativeModel("gemini-pro")
        if content_type == "Summary":
            prompt = f"""
            You are a YouTube video summarizer. Take the transcript provided and summarize it to highlight the important points in approximately {desired_word_count} words.
            Ensure the summary is concise, focused, and within the word limit of {desired_word_count} words. Provide the summary in English.
            """
        elif content_type == "Notes":
            prompt = """
            You are a YouTube video note-taker. Take the transcript provided and generate important notes that summarize the key points in a bulleted format.
            Ensure the notes are concise and focused on the most important aspects. Provide the notes in English.
            """
        elif content_type == "Flashcards":
            prompt = """
            You are a YouTube video flashcard generator. Take the transcript provided and generate a list of key concepts and questions for studying in flashcard format.
            Ensure the flashcards are clear, relevant, and easy to understand. Provide the flashcards in English.
            """
        else:
            return "Invalid content type selected."
        
        response = model.generate_content(prompt + transcript_text)
        content = response.text

        if content_type == "Summary" and desired_word_count:
            words = content.split()
            if len(words) > desired_word_count:
                content = ' '.join(words[:desired_word_count]) + '...'

        return content
    except Exception as e:
        st.error(f"Failed to generate content: {e}")
        return None

# Function to translate content
def translate_content(content, target_language):
    try:
        # Translate content to the desired language
        translated = GoogleTranslator(source='auto', target=target_language).translate(content)
        
        # Return the translated text
        return translated
    except Exception as e:
        st.error(f"Failed to translate content: {e}")
        return None

# Save content to MongoDB
def save_to_mongodb(email, video_id, content_type, content, language=None):
    try:
        content_data = {
            "email": email,
            "video_id": video_id,
            "content_type": content_type,
            "content": content,
            "language": language,
            "timestamp": datetime.datetime.utcnow()
        }
        content_collection.insert_one(content_data)
        st.success("Content saved permanently to MongoDB.")
    except Exception as e:
        st.error(f"Failed to save content to MongoDB: {e}")

# Login functionality
def login_page():
    st.title("Login")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        user = users_collection.find_one({"email": email})
        if user and bcrypt.checkpw(password.encode('utf-8'), user["password"]):
            st.session_state.logged_in = True
            st.session_state.user_email = email
            st.success("Login successful!")
        else:
            st.error("Invalid email or password.")

# Signup functionality
def signup_page():
    st.title("Sign Up")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    if st.button("Sign Up"):
        if users_collection.find_one({"email": email}):
            st.error("User already exists.")
        else:
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            users_collection.insert_one({"email": email, "password": hashed_password})
            st.session_state.logged_in = True
            st.session_state.user_email = email
            # Redirect to the login page
            st.session_state.logged_in = False  # Set logged_in state to False for redirection
            st.session_state.user_email = None  # Clear the user email
            st.success("Registration successful! You can now log in.")
            st.rerun()  # This will trigger the rerun, effectively taking the user to the login page

# Function to generate and allow the user to download the content as PDF
def generate_pdf(content, content_type):
    try:
        pdf_output = "/tmp/generated_content_reportlab.pdf"
        c = canvas.Canvas(pdf_output, pagesize=letter)
        
        # Set the title and content type in the PDF
        c.setFont("Helvetica", 16)
        c.drawString(100, 750, f"{content_type} Content")
        c.setFont("Helvetica", 12)

        # Add the generated content to the PDF with proper encoding for Unicode characters
        lines = content.split('\n')
        y = 700
        for line in lines:
            c.drawString(50, y, line)
            y -= 20  # Move to the next line
        
        # Save the PDF
        c.save()

        return pdf_output

    except Exception as e:
        print(f"Error generating PDF: {e}")
        return None

# Admin panel functionality
def admin_panel():
    st.title("Admin Panel")
    st.sidebar.subheader("Admin Actions")

    if st.button("Logout Admin"):
        st.session_state.is_admin_logged_in = False
        st.success("Admin has been logged out.")

    st.subheader("User Management")
    users = list(users_collection.find({}, {"email": 1, "_id": 0}))
    if users:
        st.write("**Registered Users:**")
        for user in users:
            st.write(f"- {user['email']}")
    else:
        st.info("No users found.")

    st.subheader("Generated Content Management")
    contents = list(content_collection.find({}, {"email": 1, "content_type": 1, "timestamp": 1, "_id": 0}))
    if contents:
        for content in contents:
            st.write(f"User: {content['email']}, Type: {content['content_type']}, Timestamp: {content['timestamp']}")
    else:
        st.info("No content generated yet.")

# Main app with content generation
def main_app():
    st.title("YouTube Transcript Summarizer")

    youtube_link = st.text_input("Enter YouTube Video Link:")
    video_id = None
    if youtube_link:
        if "v=" in youtube_link or "youtu.be/" in youtube_link:
            video_id = youtube_link.split("v=")[1].split("&")[0] if "v=" in youtube_link else youtube_link.split("youtu.be/")[1]
            st.image(f"http://img.youtube.com/vi/{video_id}/0.jpg", use_container_width=True)
        else:
            st.error("Please enter a valid YouTube link.")

    content_type = st.radio("Select the type of content to generate:", ["Summary", "Notes", "Flashcards"])

    if content_type == "Summary":
        desired_word_count = st.slider("Select the word count for the summary:", min_value=50, max_value=500, value=250, step=50)

    if "generated_content" not in st.session_state:
        st.session_state.generated_content = None
    if "translated_content" not in st.session_state:
        st.session_state.translated_content = None
    if "pdf_generated" not in st.session_state:
        st.session_state.pdf_generated = False

    if video_id:
        transcript_text = fetch_transcript(video_id)
        if transcript_text:
            if st.button("Generate Content"):
                if content_type == "Summary":
                    st.session_state.generated_content = generate_content(content_type, transcript_text, desired_word_count)
                else:
                    st.session_state.generated_content = generate_content(content_type, transcript_text, None)
                st.session_state.translated_content = None
                st.session_state.pdf_generated = False  # Reset PDF generation status

    if st.session_state.generated_content:
        st.markdown(f"<div style='padding: 10px; border: 1px solid #ccc; border-radius: 5px; background-color: #000000;'>"
                    f"<h3>{content_type} (English):</h3>"
                    f"<p>{st.session_state.generated_content}</p></div>", unsafe_allow_html=True)

        # Button to download content as PDF only if not already generated
        pdf_path = generate_pdf(st.session_state.generated_content, content_type)
        with open(pdf_path, "rb") as pdf_file:
            st.download_button(
                label="Download PDF",
                data=pdf_file,
                file_name="generated_content_reportlab.pdf",
                mime="application/pdf"
            )

        with st.expander("Translate Content"):
            translation_language = st.selectbox("Select Translation Language:", ["Hindi", "Spanish", "French", "German", "Italian"])
            if st.button("Translate Content"):
                st.session_state.translated_content = translate_content(st.session_state.generated_content, translation_language)

    if st.session_state.translated_content:
        st.markdown(f"<div style='padding: 10px; border: 1px solid #ccc; border-radius: 5px; background-color: #000000;'>"
                    f"<h3>{content_type} (Translated):</h3>"
                    f"<p>{st.session_state.translated_content}</p></div>", unsafe_allow_html=True)

# Entry point of the Streamlit app
if __name__ == "__main__":
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if "is_admin_logged_in" not in st.session_state:
        st.session_state.is_admin_logged_in = False

    if st.session_state.logged_in:
        main_app()
    elif st.session_state.is_admin_logged_in:
        admin_panel()
    else:
        option = st.sidebar.radio("Choose an option:", ["Login", "Sign Up", "Admin Login"])
        if option == "Login":
            login_page()
        elif option == "Sign Up":
            signup_page()
        elif option == "Admin Login":
            st.title("Admin Login")
            admin_email = st.text_input("Admin Email")
            admin_password = st.text_input("Admin Password", type="password")

            if st.button("Login as Admin"):
                if admin_email == ADMIN_EMAIL and admin_password == ADMIN_PASSWORD:
                    st.session_state.is_admin_logged_in = True
                    st.success("Admin login successful!")
                else:
                    st.error("Invalid admin credentials.")
