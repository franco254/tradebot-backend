from flask import Blueprint, jsonify, request
from services.scheduler import set_bot_enabled, update_strategy_config

config_bp = Blueprint('config', __name__)

@config_bp.route('/', methods=['POST'])
def save_config():
    data = request.get_json()
    update_strategy_config(data)
    return jsonify({'success': True})

@config_bp.route('/bot', methods=['POST'])
def bot_control():
    data    = request.get_json()
    enabled = data.get('enabled', True)
    set_bot_enabled(enabled)
    return jsonify({'success': True, 'bot_enabled': enabled})
