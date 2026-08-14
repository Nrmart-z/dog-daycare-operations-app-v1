import smtplib
import ssl
from email.message import EmailMessage


DEFAULT_REPORT_RECIPIENT = "nrmartz@yahoo.com"


def report_email_is_configured(settings):
    """Return True only when all required SMTP settings are present."""

    if not settings or not bool(settings.get("enabled", False)):
        return False

    required_fields = ("smtp_host", "smtp_port", "username", "password")
    return all(str(settings.get(field, "")).strip() for field in required_fields)


def send_bug_report_email(report_id, report, settings):
    """Send a saved problem report by email using approved SMTP access."""

    if not report_email_is_configured(settings):
        return False

    sender = str(settings.get("sender") or settings["username"]).strip()
    recipient = DEFAULT_REPORT_RECIPIENT
    use_ssl = bool(settings.get("use_ssl", False))
    use_starttls = bool(settings.get("use_starttls", not use_ssl))

    message = EmailMessage()
    message["Subject"] = (
        f'[Planet Bark Report #{report_id}] '
        f'{report.get("priority", "Medium")} - {report.get("title", "Problem Report")}'
    )
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        "\n".join(
            [
                f"Report ID: {report_id}",
                f"Type: {report.get('report_type') or 'Not provided'}",
                f"Priority: {report.get('priority') or 'Not provided'}",
                f"Page: {report.get('page_name') or 'Not provided'}",
                f"Employee: {report.get('reporter_name') or 'Not provided'}",
                f"Dog: {report.get('related_dog') or 'Not provided'}",
                f"Room: {report.get('related_room') or 'Not provided'}",
                "",
                f"Title: {report.get('title') or 'Not provided'}",
                "",
                "Description:",
                str(report.get("description") or "Not provided"),
                "",
                "Expected behavior:",
                str(report.get("expected_behavior") or "Not provided"),
                "",
                "Actual behavior:",
                str(report.get("actual_behavior") or "Not provided"),
                "",
                f"App version: {report.get('app_version') or '1.0.1'}",
            ]
        )
    )

    host = str(settings["smtp_host"]).strip()
    port = int(settings["smtp_port"])
    username = str(settings["username"]).strip()
    password = str(settings["password"])
    ssl_context = ssl.create_default_context()

    if use_ssl:
        with smtplib.SMTP_SSL(
            host, port, timeout=15, context=ssl_context
        ) as server:
            server.login(username, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            if use_starttls:
                server.starttls(context=ssl_context)
                server.ehlo()
            server.login(username, password)
            server.send_message(message)

    return True
