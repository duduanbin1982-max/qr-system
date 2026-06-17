"""
qr-system - QR code generation routes
"""
import base64, json
from flask import request, jsonify, g
from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.helpers import get_json_body
from modules.services.scan_qr_service import ScanQRService
from modules.middleware.error_handler import handle_unexpected_error
import qrcode as qrcode_lib
from io import BytesIO
import json as _json

@app.route('/api/qrcode/<order_no>', methods=['GET'])
@check_auth
@check_permission('scan:view')
def get_qrcode(order_no):
    try:
        order = ScanQRService.find_order_by_no(order_no)
        if not order:
            return jsonify({'error': '订单不存在'}), 404

        # QR content: order_no
        qr_data = order_no

        qr = qrcode_lib.QRCode(version=2, box_size=10, border=4)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return send_file(buf, mimetype='image/png')
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')

@app.route('/api/qrcode/batch', methods=['POST'])
@check_auth
@check_permission('scan:view')
def batch_qrcode():
    """批量生成二维码标签 - 支持订单模式和产品序列号模式"""
    try:
        data = get_json_body()
        order_ids = data.get('order_ids', [])
        mode = data.get('mode', 'order')  # 'order' 或 'serial'
        
        if not order_ids:
            return jsonify({'error': '请选择订单'}), 400

        db = get_db()
        codes = []
        skipped = []
        
        for oid in order_ids:
            order = ScanQRService.find_order_by_id(oid)
            if not order:
                continue

            # QR mode lock check
            existing_mode = (order['qr_mode'] or '').strip() if order['qr_mode'] else ''
            if existing_mode and existing_mode != mode:
                skipped.append(order['order_no'] if order['order_no'] else str(oid))
                continue

            if mode == 'serial':
                # 产品序列号模式：为每件产品生成标签
                items = ScanQRService.find_items_by_order(oid)
                
                if not items:
                    # 如果还没生成序列号，自动生成
                    items = ScanQRService.generate_serial_numbers(oid, order['order_no'], order['quantity'])
                
                # 为每个序列号生成二维码（优先使用订单中的 product_code 字段）
                product_code = (order['product_code'] or '').strip()
                if not product_code:
                    product_code = ScanQRService.find_product_code(order['product_name'])
                for item in items:
                    qr_data = f"N2{order['id']:06d}{item['position_no']:05d}"
                    qr = qrcode_lib.QRCode(version=2, box_size=8, border=1)
                    qr.add_data(qr_data)
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    buf = BytesIO()
                    img.save(buf, format='PNG')
                    buf.seek(0)
                    b64 = base64.b64encode(buf.read()).decode()
                    codes.append({
                        'serial_no': item['serial_no'],
                        'order_no': order['order_no'],
                        'customer': order['customer'],
                        'product_name': order['product_name'],
                        'product_code': product_code,
                        'position': item['position_no'],
                        'qrcode': f'data:image/png;base64,{b64}'
                    })
                db.execute('UPDATE orders SET qr_mode = ? WHERE id = ?', ('serial', oid))
            else:
                # 订单模式：每个订单一个二维码
                qr = qrcode_lib.QRCode(version=2, box_size=8, border=1)
                qr.add_data(order['order_no'])
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                buf = BytesIO()
                img.save(buf, format='PNG')
                buf.seek(0)
                b64 = base64.b64encode(buf.read()).decode()
                product_code = (order['product_code'] or '').strip()
                if not product_code:
                    product_code = ScanQRService.find_product_code(order['product_name'])
                codes.append({
                    'order_no': order['order_no'],
                    'customer': order['customer'],
                    'product_name': order['product_name'],
                    'product_code': product_code,
                    'quantity': order['quantity'],
                    'qrcode': f'data:image/png;base64,{b64}'
                    })
                db.execute('UPDATE orders SET qr_mode = ? WHERE id = ?', ('order', oid))

        db.commit()

        result = {'codes': codes}
        if skipped:
            result['skipped'] = skipped
            result['warning'] = 'Skipped locked orders: ' + ', '.join(skipped)
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')

@app.route('/api/scan/qr/<int:order_id>', methods=['GET'])
@check_auth
def generate_order_qr(order_id):
    """Generate QR code for an order (returns base64 PNG data URL)."""
    db = get_db()
    order = ScanQRService.find_order_for_qr(order_id)
    
    if not order:
        return jsonify({'error': '订单不存在'}), 404
    
    # Build QR content: compact JSON with order info
    qr_content = json.dumps({
        't': 'order',
        'id': order_id,
        'no': order['order_no'],
        'pn': order['product_name'][:30] if order['product_name'] else '',
    }, ensure_ascii=False)
    
    # Generate QR code
    qr = qrcode_lib.QRCode(
        version=2,
        error_correction=qrcode_lib.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(qr_content)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color='black', back_color='white')
    
    # Convert to base64 PNG
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    data_url = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
    
    return jsonify({
        'order_id': order_id,
        'order_no': order['order_no'],
        'qr_data_url': data_url,
        'product_name': order['product_name'],
    })
