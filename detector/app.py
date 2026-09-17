from flask import Flask, render_template, jsonify
import json
import os

app = Flask(__name__)


def load_incidents():
    if not os.path.exists("incidents.log"):
        return []
    with open("incidents.log") as f:
        return [json.loads(line) for line in f if line.strip()]


@app.route('/')
def dashboard():
    return render_template('dashboard.html')


@app.route('/api/incidents')
def api_incidents():
    return jsonify(load_incidents())


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
