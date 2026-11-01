"""Where the public site and the app live. SITE_URL (run_ui) = the public site (landing, blog, coins...);
APP_URL (optional, e.g. https://app.memesonar.app) = the logged-in tool. Without APP_URL both share one host."""
import os


def site():
    return os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")


def app():
    return os.environ.get("APP_URL", "").strip().rstrip("/")


def app_link(path):
    """Link from a public page into the app (login, dashboard): absolute once the app has its own host."""
    a = app()
    return a + path if a else path


def home_link():
    """The public front page, as linked from inside the app."""
    return site() + "/" if app() else "/dobrodosli"
