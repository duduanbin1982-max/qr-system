"""
qr-system - Email Report Routes
Sends scheduled production reports via SMTP.
"""
import json, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from flask import request, jsonify, g

from modules.app import app
from modules.db import get_db, get_setting
from modules.middleware.auth import check_auth, check_permission, audit_log

def _get_smtp_config():
    """Get SMTP config from system_settings with defaults."""
    return {
        'host': get_setting('smtp_host', ''),
        'port': int(get_setting('smtp_port', '0') or '0'),
        'user': get_setting('smtp_user', ''),
        'password': get_setting('smtp_password', ''),
        'from_email': get_setting('smtp_from', ''),
        'to_emails': get_setting('report_recipients', ''),
        'use_tls': get_setting('smtp_tls', '1') == '1',
    }

def _send_email(subject, body_html):
    """Send email using configured SMTP. Returns (success, error_msg)."""
    cfg = _get_smtp_config()
    if not cfg['host'] or not cfg['from_email']:
        return False, 'SMTP not configured (host/from required)'

    recipients = [e.strip() for e in cfg['to_emails'].split(',') if e.strip()]
    if not recipients:
        return False, 'No recipients configured'

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = cfg['from_email']
    msg['To'] = ', '.join(recipients)

    # Build HTML with inline styles
    html = '<html><body style="font-family:Arial,sans-serif;padding:20px;">'
    html += f'<h2>{subject}</h2>'
    html += body_html
    html += f'<hr><p style="color:#888;font-size:12px;">QR Production System - Auto Report</p>'
    html += '</body></html>'
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    try:
        if cfg['use_tls']:
            server = smtplib.SMTP(cfg['host'], cfg['port'], timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(cfg['host'], cfg['port'], timeout=15)
        if cfg['user']:
            server.login(cfg['user'], cfg['password'])
        server.sendmail(cfg['from_email'], recipients, msg.as_string())
        server.quit()
        return True, ''
    except Exception as e:
        return False, str(e)

def _build_daily_report():
    """Generate daily production report HTML."""
    db = get_db()
    today = datetime.now().strftime('%Y-%m-%d')

    # Today's summary
    total_orders = db.execute("SELECT COUNT(*) FROM orders WHERE date(created_at)=? AND deleted_at IS NULL", (today,)).fetchone()[0]
    new_orders = db.execute("SELECT COUNT(*) FROM orders WHERE date(created_at)=? AND status='pending' AND deleted_at IS NULL", (today,)).fetchone()[0]
    completed_orders = db.execute("SELECT COUNT(*) FROM orders WHERE date(updated_at)=? AND status='completed'", (today,)).fetchone()[0]

    # Work records today
    wr_sum = db.execute('''
        SELECT COUNT(*) as records, COALESCE(SUM(quantity),0) as qty, COUNT(DISTINCT user_id) as workers
        FROM work_records WHERE date(created_at)=?
    ''', (today,)).fetchone()

    # Top workers
    top_workers = db.execute('''
        SELECT u.name, COALESCE(SUM(wr.quantity),0) as qty, COUNT(*) as records
        FROM work_records wr
        LEFT JOIN users u ON wr.user_id = u.id
        WHERE date(wr.created_at)=?
        GROUP BY wr.user_id
        ORDER BY qty DESC LIMIT 5
    ''', (today,)).fetchall()

    # Process breakdown
    proc_breakdown = db.execute('''
        SELECT p.name, COALESCE(SUM(wr.quantity),0) as qty, COUNT(*) as records
        FROM work_records wr
        LEFT JOIN processes p ON wr.process_id = p.id
        WHERE date(wr.created_at)=?
        GROUP BY wr.process_id ORDER BY qty DESC LIMIT 10
    ''', (today,)).fetchall()

    html = f'<p>Report Date: {today}</p>'
    html += '<h3>Summary</h3>'
    html += '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">'
    html += f'<tr><td>Total Orders Today</td><td>{total_orders}</td></tr>'
    html += f'<tr><td>New Orders</td><td>{new_orders}</td></tr>'
    html += f'<tr><td>Completed Orders</td><td>{completed_orders}</td></tr>'
    html += f'<tr><td>Work Records</td><td>{wr_sum["records"]}</td></tr>'
    html += f'<tr><td>Total Quantity</td><td>{wr_sum["qty"]}</td></tr>'
    html += f'<tr><td>Active Workers</td><td>{wr_sum["workers"]}</td></tr>'
    html += '</table>'

    if top_workers:
        html += '<h3>Top Workers</h3>'
        html += '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">'
        html += '<tr><th>Worker</th><th>Quantity</th><th>Records</th></tr>'
        for w in top_workers:
            html += f'<tr><td>{w["name"] or "N/A"}</td><td>{w["qty"]}</td><td>{w["records"]}</td></tr>'
        html += '</table>'

    if proc_breakdown:
        html += '<h3>Process Breakdown</h3>'
        html += '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">'
        html += '<tr><th>Process</th><th>Quantity</th><th>Records</th></tr>'
        for p in proc_breakdown:
            html += f'<tr><td>{p["name"] or "N/A"}</td><td>{p["qty"]}</td><td>{p["records"]}</td></tr>'
        html += '</table>'

    return html


@app.route('/api/reports/email/test', methods=['POST'])
@check_auth
@check_permission('settings:manage')
def test_email_config():
    """Test SMTP configuration by sending a test email."""
    ok, err = _send_email('QR System - Test Email', '<p>This is a test email from the QR Production System.</p><p>SMTP configuration is working correctly.</p>')
    if ok:
        return jsonify({'message': 'Test email sent successfully'})
    return jsonify({'error': f'Failed to send: {err}'}), 500


@app.route('/api/reports/email/daily', methods=['POST'])
@check_auth
@check_permission('reports:view')
def send_daily_report():
    """Send daily production report email."""
    body = _build_daily_report()
    ok, err = _send_email(f'Daily Production Report - {datetime.now().strftime("%Y-%m-%d")}', body)
    if ok:
        audit_log('send_report', detail='daily report email sent')
        return jsonify({'message': 'Daily report sent'})
    return jsonify({'error': f'Failed to send: {err}'}), 500


@app.route('/api/reports/email/weekly', methods=['POST'])
@check_auth
@check_permission('reports:view')
def send_weekly_report():
    """Send weekly production report email."""
    db = get_db()
    now = datetime.now()
    week_start = (now - timedelta(days=now.weekday())).strftime('%Y-%m-%d')
    week_end = now.strftime('%Y-%m-%d')

    total_orders = db.execute("SELECT COUNT(*) FROM orders WHERE date(created_at) BETWEEN ? AND ? AND deleted_at IS NULL", (week_start, week_end)).fetchone()[0]
    completed = db.execute("SELECT COUNT(*) FROM orders WHERE date(updated_at) BETWEEN ? AND ? AND status='completed'", (week_start, week_end)).fetchone()[0]

    wr_sum = db.execute('''
        SELECT COUNT(*) as records, COALESCE(SUM(quantity),0) as qty, COUNT(DISTINCT user_id) as workers
        FROM work_records WHERE date(created_at) BETWEEN ? AND ?
    ''', (week_start, week_end)).fetchone()

    top_workers = db.execute('''
        SELECT u.name, COALESCE(SUM(wr.quantity),0) as qty
        FROM work_records wr LEFT JOIN users u ON wr.user_id = u.id
        WHERE date(wr.created_at) BETWEEN ? AND ?
        GROUP BY wr.user_id ORDER BY qty DESC LIMIT 5
    ''', (week_start, week_end)).fetchall()

    html = f'<p>Period: {week_start} to {week_end}</p>'
    html += '<h3>Weekly Summary</h3>'
    html += '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">'
    html += f'<tr><td>Total Orders</td><td>{total_orders}</td></tr>'
    html += f'<tr><td>Completed</td><td>{completed}</td></tr>'
    html += f'<tr><td>Work Records</td><td>{wr_sum["records"]}</td></tr>'
    html += f'<tr><td>Total Quantity</td><td>{wr_sum["qty"]}</td></tr>'
    html += f'<tr><td>Active Workers</td><td>{wr_sum["workers"]}</td></tr>'
    html += '</table>'

    if top_workers:
        html += '<h3>Top Workers</h3>'
        html += '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">'
        html += '<tr><th>Worker</th><th>Quantity</th></tr>'
        for w in top_workers:
            html += f'<tr><td>{w["name"] or "N/A"}</td><td>{w["qty"]}</td></tr>'
        html += '</table>'

    ok, err = _send_email(f'Weekly Production Report - {week_start} to {week_end}', html)
    if ok:
        audit_log('send_report', detail='weekly report email sent')
        return jsonify({'message': 'Weekly report sent'})
    return jsonify({'error': f'Failed to send: {err}'}), 500