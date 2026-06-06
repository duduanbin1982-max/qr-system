module.exports = {
  apps: [{
    name: 'qr-system',
    script: '/home/dubin/.local/bin/gunicorn',
    args: '-c gunicorn.conf.py server:app',
    interpreter: 'none',
    cwd: '/home/dubin/qr-system',
    autorestart: true,
    max_restarts: 10,
    min_uptime: '3s',
    max_memory_restart: '300M',
    error_file: '/home/dubin/qr-system/logs/error.log',
    out_file: '/home/dubin/qr-system/logs/out.log',
    merge_logs: true,
    time: true,
    env: {
      SECRET_KEY: '1d0cf9fe2aa958d4300e53fc02e09243c1d4d324b13c1fff18507aa3badea773'
    }
  }]
};
