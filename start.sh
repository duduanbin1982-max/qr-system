cd ~/qr-system
export PATH=$HOME/.local/bin:$PATH
nohup gunicorn -c gunicorn.conf.py server:app > logs/gunicorn.log 2>&1 &
echo "Started PID: $!"
