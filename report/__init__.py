"""Daily morning report: aggregates the bot's databases, lets Claude interpret them, renders an email-safe HTML
and sends it (SMTP or Resend). Read-only on every database; writes only $DATA_DIR/output/report-*.html (last 14)
and output/report-state.json. Entry point: run_report.py."""
