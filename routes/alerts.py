from flask import Blueprint, jsonify
from services.scheduler import get_pending_alerts

alerts_bp = Blueprint('alerts', __name__)

@alerts_bp.route('/pending', methods=['GET'])
def pending():
    """
    Returns and clears pending alerts.
    The Android app polls this every 30s.
    """
    return jsonify(get_pending_alerts())
