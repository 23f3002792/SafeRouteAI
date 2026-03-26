from dotenv import load_dotenv
load_dotenv()  # load .env before anything else imports os.getenv()

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
